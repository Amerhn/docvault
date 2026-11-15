"""Teams: create, search, join by request or by invite link, members and owners."""
import hashlib
import hmac
import re
import secrets
import sqlite3
from typing import List, Optional

from .db import parse_ts, utc_in, utcnow
from .services import AppError

ROLES = ("owner", "member")


def _clean_team_name(name: Optional[str]) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not 2 <= len(name) <= 60:
        raise AppError("The team name must be 2 to 60 characters.")
    return name


def role_in(conn: sqlite3.Connection, user_id: int, team_id: int) -> Optional[str]:
    row = conn.execute("SELECT role FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id)).fetchone()
    return row["role"] if row else None


def require_member(conn: sqlite3.Connection, user_id: int, team_id: int) -> str:
    role = role_in(conn, user_id, team_id)
    if role is None:
        raise AppError("You are not a member of this team.", 403)
    return role


def require_owner(conn: sqlite3.Connection, user_id: int, team_id: int) -> None:
    if require_member(conn, user_id, team_id) != "owner":
        raise AppError("Only a team owner can do this.", 403)


def _team_row(conn, team_id: int):
    row = conn.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
    if row is None:
        raise AppError("Team not found.", 404)
    return row


def _member_count(conn, team_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM team_members WHERE team_id = ?", (team_id,)).fetchone()[0]


def _owner_count(conn, team_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM team_members WHERE team_id = ? AND role = 'owner'", (team_id,)).fetchone()[0]


# ------------------------------------------------------------------ teams
def create_team(conn: sqlite3.Connection, user: dict, name: str, description: str = "") -> dict:
    name = _clean_team_name(name)
    description = (description or "").strip()[:300]
    try:
        with conn:
            tid = conn.execute("INSERT INTO teams (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
                               (name, description, user["user_id"], utcnow())).lastrowid
            conn.execute("INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                         (tid, user["user_id"], utcnow()))
    except sqlite3.IntegrityError:
        raise AppError("A team with that name already exists. Choose another name.", 409)
    return team_info(conn, user, tid)


def team_info(conn: sqlite3.Connection, user: dict, team_id: int) -> dict:
    t = _team_row(conn, team_id)
    return {"team_id": t["team_id"], "name": t["name"], "description": t["description"],
            "is_discoverable": bool(t["is_discoverable"]), "member_count": _member_count(conn, team_id),
            "role": role_in(conn, user["user_id"], team_id), "created_at": t["created_at"]}


def my_teams(conn: sqlite3.Connection, user_id: int) -> List[dict]:
    rows = conn.execute("SELECT t.team_id FROM team_members m JOIN teams t ON t.team_id = m.team_id "
                        "WHERE m.user_id = ? ORDER BY lower(t.name)", (user_id,)).fetchall()
    return [team_info(conn, {"user_id": user_id}, r["team_id"]) for r in rows]


def update_team(conn: sqlite3.Connection, user: dict, team_id: int, name: Optional[str] = None,
                description: Optional[str] = None, is_discoverable: Optional[bool] = None) -> dict:
    require_owner(conn, user["user_id"], team_id)
    try:
        with conn:
            if name is not None:
                conn.execute("UPDATE teams SET name = ? WHERE team_id = ?", (_clean_team_name(name), team_id))
            if description is not None:
                conn.execute("UPDATE teams SET description = ? WHERE team_id = ?", (description.strip()[:300], team_id))
            if is_discoverable is not None:
                conn.execute("UPDATE teams SET is_discoverable = ? WHERE team_id = ?", (int(is_discoverable), team_id))
    except sqlite3.IntegrityError:
        raise AppError("A team with that name already exists. Choose another name.", 409)
    return team_info(conn, user, team_id)


def search_teams(conn: sqlite3.Connection, user: dict, query: str) -> List[dict]:
    q = (query or "").strip()
    if len(q) < 2:
        raise AppError("Type at least 2 letters of the team name.")
    like = "%" + q.replace("%", "").replace("_", "") + "%"
    rows = conn.execute("SELECT * FROM teams WHERE is_discoverable = 1 AND name LIKE ? ORDER BY lower(name) LIMIT 20",
                        (like,)).fetchall()
    out = []
    for t in rows:
        req = conn.execute("SELECT status FROM join_requests WHERE team_id = ? AND user_id = ? ORDER BY request_id DESC LIMIT 1",
                           (t["team_id"], user["user_id"])).fetchone()
        out.append({"team_id": t["team_id"], "name": t["name"], "description": t["description"],
                    "member_count": _member_count(conn, t["team_id"]),
                    "is_member": role_in(conn, user["user_id"], t["team_id"]) is not None,
                    "request_status": req["status"] if req else None})
    return out


def members(conn: sqlite3.Connection, user: dict, team_id: int) -> List[dict]:
    require_member(conn, user["user_id"], team_id)
    rows = conn.execute(
        "SELECT u.user_id, u.username, COALESCE(u.display_name, u.username) AS display_name, u.has_avatar, "
        "m.role, m.joined_at FROM team_members m JOIN users u ON u.user_id = m.user_id "
        "WHERE m.team_id = ? ORDER BY (m.role = 'owner') DESC, lower(COALESCE(u.display_name, u.username))", (team_id,))
    return [dict(r) | {"has_avatar": bool(r["has_avatar"])} for r in rows]


def set_role(conn: sqlite3.Connection, user: dict, team_id: int, member_id: int, role: str) -> None:
    require_owner(conn, user["user_id"], team_id)
    if role not in ROLES:
        raise AppError("Role must be 'owner' or 'member'.")
    if role_in(conn, member_id, team_id) is None:
        raise AppError("That person is not in this team.", 404)
    if role == "member" and role_in(conn, member_id, team_id) == "owner" and _owner_count(conn, team_id) <= 1:
        raise AppError("A team needs at least one owner.")
    with conn:
        conn.execute("UPDATE team_members SET role = ? WHERE team_id = ? AND user_id = ?", (role, team_id, member_id))


def remove_member(conn: sqlite3.Connection, user: dict, team_id: int, member_id: int) -> None:
    """An owner removes someone, or any member leaves (member_id is their own id)."""
    if member_id == user["user_id"]:
        require_member(conn, user["user_id"], team_id)
    else:
        require_owner(conn, user["user_id"], team_id)
        if role_in(conn, member_id, team_id) is None:
            raise AppError("That person is not in this team.", 404)
    if role_in(conn, member_id, team_id) == "owner" and _owner_count(conn, team_id) <= 1:
        raise AppError("A team needs at least one owner. Make someone else an owner first.")
    with conn:
        conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, member_id))


# ------------------------------------------------------------------ join requests (search, then ask)
def request_join(conn: sqlite3.Connection, user: dict, team_id: int) -> None:
    t = _team_row(conn, team_id)
    if role_in(conn, user["user_id"], team_id):
        raise AppError("You are already in this team.")
    if not t["is_discoverable"]:
        raise AppError("Team not found.", 404)
    if conn.execute("SELECT 1 FROM join_requests WHERE team_id = ? AND user_id = ? AND status = 'pending'",
                    (team_id, user["user_id"])).fetchone():
        raise AppError("You already asked to join this team. Wait for an owner to answer.")
    with conn:
        conn.execute("INSERT INTO join_requests (team_id, user_id, created_at) VALUES (?, ?, ?)",
                     (team_id, user["user_id"], utcnow()))


def pending_requests(conn: sqlite3.Connection, user: dict, team_id: int) -> List[dict]:
    require_owner(conn, user["user_id"], team_id)
    rows = conn.execute(
        "SELECT r.request_id, r.created_at, u.user_id, u.username, COALESCE(u.display_name, u.username) AS display_name, "
        "u.email FROM join_requests r JOIN users u ON u.user_id = r.user_id "
        "WHERE r.team_id = ? AND r.status = 'pending' ORDER BY r.request_id", (team_id,))
    return [dict(r) for r in rows]


def decide_request(conn: sqlite3.Connection, user: dict, request_id: int, approve: bool) -> None:
    r = conn.execute("SELECT * FROM join_requests WHERE request_id = ?", (request_id,)).fetchone()
    if r is None:
        raise AppError("Request not found.", 404)
    require_owner(conn, user["user_id"], r["team_id"])
    if r["status"] != "pending":
        raise AppError("This request was already answered.")
    with conn:
        conn.execute("UPDATE join_requests SET status = ?, decided_by = ?, decided_at = ? WHERE request_id = ?",
                     ("approved" if approve else "declined", user["user_id"], utcnow(), request_id))
        if approve and role_in(conn, r["user_id"], r["team_id"]) is None:
            conn.execute("INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                         (r["team_id"], r["user_id"], utcnow()))


# ------------------------------------------------------------------ invite links
def _token_hash(settings, token: str) -> str:
    return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_invite(conn: sqlite3.Connection, settings, user: dict, team_id: int) -> dict:
    """The token is shown ONCE, here. Only its hash is stored."""
    require_owner(conn, user["user_id"], team_id)
    token = secrets.token_urlsafe(24)
    expires = utc_in(settings.invite_days * 86400)
    with conn:
        iid = conn.execute(
            "INSERT INTO team_invites (team_id, token_hash, created_by, created_at, expires_at, max_uses) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (team_id, _token_hash(settings, token), user["user_id"], utcnow(), expires, settings.invite_max_uses)).lastrowid
    return {"invite_id": iid, "token": token, "expires_at": expires, "max_uses": settings.invite_max_uses}


def list_invites(conn: sqlite3.Connection, user: dict, team_id: int) -> List[dict]:
    require_owner(conn, user["user_id"], team_id)
    rows = conn.execute(
        "SELECT i.invite_id, i.created_at, i.expires_at, i.max_uses, i.uses, COALESCE(u.display_name, u.username) AS created_by "
        "FROM team_invites i JOIN users u ON u.user_id = i.created_by "
        "WHERE i.team_id = ? AND i.revoked = 0 AND i.expires_at > ? ORDER BY i.invite_id DESC", (team_id, utcnow()))
    return [dict(r) for r in rows]


def revoke_invite(conn: sqlite3.Connection, user: dict, invite_id: int) -> None:
    row = conn.execute("SELECT team_id FROM team_invites WHERE invite_id = ?", (invite_id,)).fetchone()
    if row is None:
        raise AppError("Invite not found.", 404)
    require_owner(conn, user["user_id"], row["team_id"])
    with conn:
        conn.execute("UPDATE team_invites SET revoked = 1 WHERE invite_id = ?", (invite_id,))


def accept_invite(conn: sqlite3.Connection, settings, user: dict, token: str) -> dict:
    bad = AppError("This invite link is not valid any more. Ask for a new one.", 400)
    row = conn.execute("SELECT * FROM team_invites WHERE token_hash = ?", (_token_hash(settings, (token or "").strip()),)).fetchone()
    if row is None or row["revoked"] or row["expires_at"] < utcnow() or row["uses"] >= row["max_uses"]:
        raise bad
    if role_in(conn, user["user_id"], row["team_id"]) is None:
        with conn:
            conn.execute("INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                         (row["team_id"], user["user_id"], utcnow()))
            conn.execute("UPDATE team_invites SET uses = uses + 1 WHERE invite_id = ?", (row["invite_id"],))
            # an invite makes any waiting request unnecessary
            conn.execute("UPDATE join_requests SET status = 'approved', decided_at = ? WHERE team_id = ? AND user_id = ? "
                         "AND status = 'pending'", (utcnow(), row["team_id"], user["user_id"]))
    return team_info(conn, user, row["team_id"])
