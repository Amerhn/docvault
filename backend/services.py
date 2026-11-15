"""Application logic: AuthService and VersionService (Figure 3.6). No web code in here."""
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from .db import parse_ts, utc_in, utcnow
from .mailer import MailError
from .security import create_token, hash_password, verify_password
from .storage import StorageError

log = logging.getLogger("docvault")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = ("user", "admin")
MAX_MESSAGE = 500
_DUMMY_HASH = hash_password("not-a-real-password")


class AppError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------------ helpers
def clean_filename(name: Optional[str]) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    if not name or name in (".", ".."):
        raise AppError("The file needs a valid name.")
    if len(name) > 200:
        raise AppError("The file name is too long (200 characters at most).")
    return name


def clean_message(message: Optional[str]) -> str:
    message = (message or "").strip()
    if not message:
        raise AppError("Enter a commit message.")
    if len(message) > MAX_MESSAGE:
        raise AppError("The commit message is too long (%d characters at most)." % MAX_MESSAGE)
    return message


def public_user(row) -> dict:
    return {"user_id": row["user_id"], "username": row["username"], "role": row["role"],
            "is_active": bool(row["is_active"]), "locked": False, "email": row["email"],
            "must_change_password": bool(row["must_change_password"]),
            "display_name": row["display_name"] or row["username"], "theme": row["theme"],
            "has_avatar": bool(row["has_avatar"]), "email_verified": bool(row["email_verified"]),
            "created_at": row["created_at"]}


def clean_password(password: Optional[str]) -> str:
    if len(password or "") < 8:
        raise AppError("Password must be at least 8 characters.")
    return password


# ------------------------------------------------------------------ AuthService
def create_user(conn: sqlite3.Connection, username: str, password: str, role: str = "user",
                email: Optional[str] = None, must_change: bool = False) -> dict:
    """Admin-created accounts use must_change=True: the user picks their own password at first login."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AppError("Username must be 3 to 50 characters: letters, digits, dot, dash, or underscore.")
    clean_password(password)
    if role not in ROLES:
        raise AppError("Role must be 'user' or 'admin'.")
    email = (email or "").strip().lower() or None
    if email and (len(email) > 120 or not EMAIL_RE.match(email)):
        raise AppError("Enter a valid email address, or leave it empty.")
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, email, must_change_password, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, hash_password(password), role, email, int(must_change), utcnow()))
    except sqlite3.IntegrityError:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AppError("That username already exists.", 409)
        raise AppError("That email address is already used by another account.", 409)
    return public_user(conn.execute("SELECT * FROM users WHERE user_id = ?", (cur.lastrowid,)).fetchone())


def find_user(conn: sqlite3.Connection, identifier: str):
    """Find an account by username (any capitals) or by email address. An exact username match wins."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    return conn.execute("SELECT * FROM users WHERE lower(username) = lower(?) OR email = ? ORDER BY (username = ?) DESC LIMIT 1",
                        (ident, ident.lower(), ident)).fetchone()


def _login_result(settings, row) -> dict:
    token = create_token(settings.secret_key, row["user_id"], row["role"], settings.token_hours)
    return {"token": token, "user": public_user(row)}


def _is_locked(conn: sqlite3.Connection, settings, row) -> bool:
    """Locked after too many wrong passwords, but only for settings.lock_minutes after the last wrong one."""
    if row["failed_attempts"] < settings.max_failed_attempts:
        return False
    last = conn.execute("SELECT logged_at FROM login_log WHERE user_id = ? AND success = 0 ORDER BY log_id DESC LIMIT 1",
                        (row["user_id"],)).fetchone()
    if last is not None and (parse_ts(utcnow()) - parse_ts(last["logged_at"])).total_seconds() < settings.lock_minutes * 60:
        return True
    with conn:                                   # the waiting time is over: open the account again
        conn.execute("UPDATE users SET failed_attempts = 0 WHERE user_id = ?", (row["user_id"],))
    return False


def authenticate(conn: sqlite3.Connection, settings, username: str, password: str) -> dict:
    """Log in with a username or an email address. An empty field never counts as a wrong password."""
    ident = (username or "").strip()
    if not ident or not password:
        raise AppError("Enter your email or username and your password.", 400)
    row = find_user(conn, ident)
    if row is None:
        verify_password(password, _DUMMY_HASH)                 # same cost as a real login
        log.info("Login refused: no account matches '%s'.", ident)
        raise AppError("Invalid username or password.", 401)
    if not row["is_active"]:
        log.info("Login refused: account '%s' is disabled.", row["username"])
        raise AppError("This account is disabled.", 403)
    if _is_locked(conn, settings, row):
        log.info("Login refused: account '%s' is locked.", row["username"])
        raise AppError("Account locked after too many wrong passwords. Wait %d minutes, or use Forgot password to unlock it now."
                       % settings.lock_minutes, 423)
    ok = verify_password(password, row["password_hash"])
    with conn:
        conn.execute("INSERT INTO login_log (user_id, logged_at, success) VALUES (?, ?, ?)",
                     (row["user_id"], utcnow(), int(ok)))
        if ok:
            conn.execute("UPDATE users SET failed_attempts = 0 WHERE user_id = ?", (row["user_id"],))
        else:
            conn.execute("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE user_id = ?", (row["user_id"],))
    if not ok:
        left = settings.max_failed_attempts - (row["failed_attempts"] + 1)
        log.info("Login refused: wrong password for '%s' (%d tries left).", row["username"], max(left, 0))
        extra = (" You have %d more %s before the account is locked." % (left, "try" if left == 1 else "tries")) if left > 0 else ""
        raise AppError("Invalid username or password." + extra, 401)
    if not row["email_verified"]:
        raise AppError("Please verify your email address first. Use the Verify tab to enter the code we sent.", 403)
    return _login_result(settings, row)


def list_users(conn: sqlite3.Connection, settings) -> List[dict]:
    out = []
    for row in conn.execute("SELECT * FROM users ORDER BY username"):
        u = public_user(row)
        u["locked"] = _is_locked(conn, settings, row)
        out.append(u)
    return out


def set_user_active(conn: sqlite3.Connection, user_id: int, active: bool) -> None:
    with conn:
        cur = conn.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (int(active), user_id))
    if cur.rowcount == 0:
        raise AppError("User not found.", 404)


def reset_user(conn: sqlite3.Connection, user_id: int, new_password: Optional[str] = None) -> None:
    """Unlock an account and, if a new password is given, replace the password."""
    if new_password is not None:
        clean_password(new_password)
    with conn:
        if new_password is not None:      # a password set by an administrator is temporary
            cur = conn.execute("UPDATE users SET password_hash = ?, failed_attempts = 0, must_change_password = 1 "
                               "WHERE user_id = ?", (hash_password(new_password), user_id))
        else:
            cur = conn.execute("UPDATE users SET failed_attempts = 0 WHERE user_id = ?", (user_id,))
    if cur.rowcount == 0:
        raise AppError("User not found.", 404)


def change_password(conn: sqlite3.Connection, user_id: int, current_password: str, new_password: str) -> None:
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or not verify_password(current_password or "", row["password_hash"]):
        raise AppError("The current password is not correct.", 400)
    clean_password(new_password)
    if new_password == current_password:
        raise AppError("Choose a password that is different from the current one.")
    with conn:
        conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE user_id = ?",
                     (hash_password(new_password), user_id))


def _code_hash(settings, user_id: int, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), ("%d:%s" % (user_id, code)).encode(), hashlib.sha256).hexdigest()


def _issue_code(conn, settings, table: str, user_id: int) -> Optional[str]:
    """Create a 6-digit code in `table`. Returns None when asked again too soon."""
    last = conn.execute("SELECT created_at FROM %s WHERE user_id = ? ORDER BY rowid DESC LIMIT 1" % table,
                        (user_id,)).fetchone()
    if last and (parse_ts(utcnow()) - parse_ts(last["created_at"])).total_seconds() < settings.reset_cooldown_seconds:
        return None
    code = "%06d" % secrets.randbelow(10 ** 6)
    with conn:
        conn.execute("UPDATE %s SET used = 1 WHERE user_id = ? AND used = 0" % table, (user_id,))
        conn.execute("INSERT INTO %s (user_id, code_hash, created_at, expires_at) VALUES (?, ?, ?, ?)" % table,
                     (user_id, _code_hash(settings, user_id, code), utcnow(), utc_in(settings.reset_minutes * 60)))
    return code


def _check_code(conn, settings, table: str, user_id: int, code: str) -> bool:
    """True once, for the right code. Wrong guesses are counted and limited."""
    r = conn.execute("SELECT rowid AS rid, * FROM %s WHERE user_id = ? AND used = 0 ORDER BY rowid DESC LIMIT 1" % table,
                     (user_id,)).fetchone()
    if r is None or r["expires_at"] < utcnow() or r["attempts"] >= settings.reset_max_attempts:
        return False
    if not hmac.compare_digest(r["code_hash"], _code_hash(settings, user_id, (code or "").strip())):
        with conn:
            conn.execute("UPDATE %s SET attempts = attempts + 1 WHERE rowid = ?" % table, (r["rid"],))
        return False
    with conn:
        conn.execute("UPDATE %s SET used = 1 WHERE rowid = ?" % table, (r["rid"],))
    return True


def request_reset(conn: sqlite3.Connection, settings, mailer, identifier: str) -> None:
    """Email a 6-digit code to the account's address. Says nothing about whether the account exists."""
    row = find_user(conn, identifier)
    if row is None or not row["is_active"] or not row["email"]:
        log.info("Reset code not sent for '%s': no active account with an email address.", (identifier or "").strip())
        return
    code = _issue_code(conn, settings, "password_resets", row["user_id"])
    if code is None:
        log.info("Reset code not sent for '%s': a code was sent less than %d seconds ago.", row["username"], settings.reset_cooldown_seconds)
        return
    body = ("Your DocVault password reset code is: %s\n\nIt works for %d minutes. "
            "If you did not ask for it, ignore this email and your password stays the same."
            % (code, settings.reset_minutes))
    try:
        mailer.send(row["email"], "DocVault password reset code", body)
    except MailError:
        log.exception("Could not send the reset code to user %s", row["user_id"])


def reset_password(conn: sqlite3.Connection, settings, identifier: str, code: str, new_password: str) -> None:
    bad = AppError("The code is wrong or has expired. Ask for a new code.", 400)
    row = find_user(conn, identifier)
    if row is None:
        raise bad
    clean_password(new_password)
    if not _check_code(conn, settings, "password_resets", row["user_id"], code):
        raise bad
    with conn:
        conn.execute("UPDATE users SET password_hash = ?, failed_attempts = 0, must_change_password = 0 "
                     "WHERE user_id = ?", (hash_password(new_password), row["user_id"]))


# ------------------------------------------------------------------ sign-up and email check
def _free_username(conn: sqlite3.Connection, email: str) -> str:
    base = re.sub(r"[^a-z0-9_.-]", "", email.split("@")[0].lower()) or "user"
    base = (base + "user")[:30] if len(base) < 3 else base[:30]
    name, n = base, 1
    while conn.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone():
        n += 1
        name = "%s%d" % (base, n)
    return name


def _send_verification(conn, settings, mailer, row) -> None:
    code = _issue_code(conn, settings, "email_verifications", row["user_id"])
    if code is None:
        return
    body = ("Welcome to DocVault. Your email verification code is: %s\n\nIt works for %d minutes. "
            "If you did not create an account, ignore this email." % (code, settings.reset_minutes))
    try:
        mailer.send(row["email"], "Verify your DocVault email", body)
    except MailError:
        log.exception("Could not send the verification code to user %s", row["user_id"])


def signup(conn: sqlite3.Connection, settings, mailer, full_name: str, email: str, password: str) -> dict:
    full_name = re.sub(r"\s+", " ", (full_name or "").strip())
    email = (email or "").strip().lower()
    if not 2 <= len(full_name) <= 80:
        raise AppError("Enter your name (2 to 80 characters).")
    if len(email) > 120 or not EMAIL_RE.match(email):
        raise AppError("Enter a valid email address.")
    clean_password(password)
    existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        if existing["email_verified"]:
            raise AppError("An account with this email already exists. Log in instead.", 409)
        _send_verification(conn, settings, mailer, existing)          # unverified: send a fresh code
        return {"detail": "We sent a verification code to %s." % email}
    with conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, email, display_name, email_verified, created_at) "
            "VALUES (?, ?, 'user', ?, ?, 0, ?)",
            (_free_username(conn, email), hash_password(password), email, full_name, utcnow()))
    _send_verification(conn, settings, mailer, conn.execute("SELECT * FROM users WHERE user_id = ?", (cur.lastrowid,)).fetchone())
    return {"detail": "We sent a verification code to %s." % email}


def resend_verification(conn: sqlite3.Connection, settings, mailer, email: str) -> None:
    row = conn.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    if row is not None and not row["email_verified"] and row["is_active"]:
        _send_verification(conn, settings, mailer, row)


def verify_email(conn: sqlite3.Connection, settings, email: str, code: str) -> dict:
    bad = AppError("The code is wrong or has expired. Ask for a new code.", 400)
    row = conn.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    if row is None or row["email_verified"]:
        raise bad
    if not _check_code(conn, settings, "email_verifications", row["user_id"], code):
        raise bad
    with conn:
        conn.execute("UPDATE users SET email_verified = 1 WHERE user_id = ?", (row["user_id"],))
    return _login_result(settings, conn.execute("SELECT * FROM users WHERE user_id = ?", (row["user_id"],)).fetchone())


# ------------------------------------------------------------------ profile, themes, avatar
THEMES = ("light", "dark", "paper", "silver", "graphite", "sky", "mint", "violet", "amber", "blush", "indigo", "aurora")
MAX_AVATAR_BYTES = 3 * 1024 * 1024


def get_profile(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise AppError("User not found.", 404)
    prof = public_user(row)
    prof["teams"] = [dict(r) for r in conn.execute(
        "SELECT t.team_id, t.name, m.role FROM team_members m JOIN teams t ON t.team_id = m.team_id "
        "WHERE m.user_id = ? ORDER BY t.name", (user_id,))]
    return prof


def update_profile(conn: sqlite3.Connection, user_id: int, display_name: Optional[str] = None,
                   theme: Optional[str] = None) -> dict:
    with conn:
        if display_name is not None:
            name = re.sub(r"\s+", " ", display_name.strip())
            if not 2 <= len(name) <= 80:
                raise AppError("Your name must be 2 to 80 characters.")
            conn.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (name, user_id))
        if theme is not None:
            if theme not in THEMES:
                raise AppError("Unknown theme.")
            conn.execute("UPDATE users SET theme = ? WHERE user_id = ?", (theme, user_id))
    return get_profile(conn, user_id)


def _avatar_path(settings, user_id: int) -> str:
    import os
    return os.path.join(settings.avatar_dir, "%d.png" % user_id)


def save_avatar(conn: sqlite3.Connection, settings, user_id: int, data: bytes) -> None:
    import io
    import os
    if len(data) > MAX_AVATAR_BYTES:
        raise AppError("The picture is larger than 3 MB.", 413)
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover
        raise AppError("Profile pictures need the Pillow package (pip install Pillow).", 500)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        raise AppError("That file is not a picture we can read (use PNG or JPG).")
    img = ImageOps.fit(img, (256, 256))
    os.makedirs(settings.avatar_dir, exist_ok=True)
    img.save(_avatar_path(settings, user_id), "PNG")
    with conn:
        conn.execute("UPDATE users SET has_avatar = 1 WHERE user_id = ?", (user_id,))


def remove_avatar(conn: sqlite3.Connection, settings, user_id: int) -> None:
    import os
    try:
        os.remove(_avatar_path(settings, user_id))
    except FileNotFoundError:
        pass
    with conn:
        conn.execute("UPDATE users SET has_avatar = 0 WHERE user_id = ?", (user_id,))


def avatar_bytes(conn: sqlite3.Connection, settings, user_id: int) -> bytes:
    row = conn.execute("SELECT has_avatar FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or not row["has_avatar"]:
        raise AppError("No picture.", 404)
    try:
        with open(_avatar_path(settings, user_id), "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        raise AppError("No picture.", 404)


# ------------------------------------------------------------------ who may see a file
def _is_member(conn: sqlite3.Connection, user_id: int, team_id: int) -> bool:
    return conn.execute("SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id)).fetchone() is not None


def require_workspace(conn: sqlite3.Connection, user_id: int, team_id: Optional[int]) -> None:
    if team_id is not None and not _is_member(conn, user_id, team_id):
        raise AppError("You are not a member of this team.", 403)


def file_access(conn: sqlite3.Connection, user_id: int, file_id: int):
    """The file row if this user may use it, otherwise a 404 (we do not reveal that it exists)."""
    f = conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
    if f is None:
        raise AppError("File not found.", 404)
    allowed = f["created_by"] == user_id if f["team_id"] is None else _is_member(conn, user_id, f["team_id"])
    if not allowed:
        raise AppError("File not found.", 404)
    return f


_KEY_RE = re.compile(r"^([ut])(\d+)/(.+)$")


# ------------------------------------------------------------------ VersionService
class VersionService:
    def __init__(self, conn: sqlite3.Connection, storage, settings):
        self.conn = conn
        self.storage = storage
        self.settings = settings

    # ---- reading
    def _file(self, file_id: int):
        row = self.conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
        if row is None:
            raise AppError("File not found.", 404)
        return row

    def _version_rows(self, file_id: int):
        return self.conn.execute(
            "SELECT v.*, u.username AS author FROM versions v JOIN users u ON u.user_id = v.uploaded_by "
            "WHERE v.file_id = ? ORDER BY v.uploaded_at, v.version_id", (file_id,)).fetchall()

    def list_versions(self, file_id: int) -> List[dict]:
        self._file(file_id)
        rows = self._version_rows(file_id)
        number = {r["version_id"]: i + 1 for i, r in enumerate(rows)}
        out = []
        for i, r in enumerate(rows):
            out.append({
                "version_id": r["version_id"], "version_no": i + 1, "author": r["author"],
                "uploaded_at": r["uploaded_at"], "size_bytes": r["size_bytes"],
                "commit_message": r["commit_message"], "is_rollback": bool(r["is_rollback"]),
                "source_version_no": number.get(r["source_version_id"]),
                "is_current": i == len(rows) - 1,
            })
        return out

    def _scope_sql(self, team_id: Optional[int], owner_id: Optional[int]):
        """Filter on files f: one team, one person's private files, or (for tests and maintenance) everything."""
        if team_id is not None:
            return " AND f.team_id = ?", [team_id]
        if owner_id is not None:
            return " AND f.team_id IS NULL AND f.created_by = ?", [owner_id]
        return "", []

    def list_files(self, team_id: Optional[int] = None, owner_id: Optional[int] = None) -> List[dict]:
        where, args = self._scope_sql(team_id, owner_id)
        out = []
        for f in self.conn.execute("SELECT f.* FROM files f WHERE 1 = 1" + where, args).fetchall():
            rows = self._version_rows(f["file_id"])
            if not rows:
                continue
            last = rows[-1]
            out.append({"file_id": f["file_id"], "file_name": f["file_name"], "version_count": len(rows),
                        "last_modified": last["uploaded_at"], "last_author": last["author"],
                        "size_bytes": last["size_bytes"], "last_message": last["commit_message"]})
        out.sort(key=lambda x: x["last_modified"], reverse=True)
        return out

    def history_all(self, limit: int = 200, team_id: Optional[int] = None, owner_id: Optional[int] = None) -> List[dict]:
        where, args = self._scope_sql(team_id, owner_id)
        rows = self.conn.execute(
            "SELECT v.version_id, v.uploaded_at, v.size_bytes, v.commit_message, v.is_rollback, "
            "f.file_name, u.username AS author, COALESCE(u.display_name, u.username) AS author_name "
            "FROM versions v JOIN files f ON f.file_id = v.file_id JOIN users u ON u.user_id = v.uploaded_by "
            "WHERE 1 = 1" + where + " ORDER BY v.uploaded_at DESC, v.version_id DESC LIMIT ?", args + [limit]).fetchall()
        return [dict(r) | {"is_rollback": bool(r["is_rollback"])} for r in rows]

    # ---- writing
    def _insert_version(self, file_id: int, s3_version_id: str, user_id: int, size: int, message: str,
                        is_rollback: bool = False, source_version_id: Optional[int] = None,
                        uploaded_at: Optional[str] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO versions (file_id, s3_version_id, uploaded_by, uploaded_at, size_bytes, commit_message, "
            "is_rollback, source_version_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, s3_version_id, user_id, uploaded_at or utcnow(), size, message, int(is_rollback), source_version_id))
        return cur.lastrowid

    def upload(self, user: dict, filename: str, data: bytes, message: str, team_id: Optional[int] = None) -> dict:
        name = clean_filename(filename)
        require_workspace(self.conn, user["user_id"], team_id)
        key = ("t%d/%s" % (team_id, name)) if team_id is not None else ("u%d/%s" % (user["user_id"], name))
        message = clean_message(message)
        if len(data) == 0:
            raise AppError("The file is empty.")
        if len(data) > self.settings.max_upload_mb * 1024 * 1024:
            raise AppError("The file is larger than %d MB." % self.settings.max_upload_mb, 413)
        meta = {"commit-message": quote(message), "author": quote(user["username"])}
        try:
            s3_version_id = self.storage.put_object(key, data, meta)       # storage first ...
        except StorageError as exc:
            raise AppError(str(exc), 502)
        try:
            with self.conn:                                                # ... then the record
                row = self.conn.execute("SELECT file_id FROM files WHERE s3_key = ?", (key,)).fetchone()
                if row is None:
                    cur = self.conn.execute(
                        "INSERT INTO files (file_name, s3_key, created_by, created_at, team_id) VALUES (?, ?, ?, ?, ?)",
                        (name, key, user["user_id"], utcnow(), team_id))
                    file_id = cur.lastrowid
                else:
                    file_id = row["file_id"]
                self._insert_version(file_id, s3_version_id, user["user_id"], len(data), message)
        except sqlite3.Error:
            log.exception("Saved to storage but failed to record the version of %s", key)
            raise AppError("The file was stored, but its record could not be saved. "
                           "Ask an administrator to run a re-sync.", 500)
        return {"file_id": file_id, "versions": self.list_versions(file_id)}

    def rollback(self, user: dict, file_id: int, version_id: int, message: Optional[str] = None) -> dict:
        f = self._file(file_id)
        versions = self.list_versions(file_id)
        target = next((v for v in versions if v["version_id"] == version_id), None)
        if target is None:
            raise AppError("That version does not belong to this file.", 404)
        if target["is_current"]:
            raise AppError("This is already the current version.")
        message = clean_message(message) if (message or "").strip() else "Rollback to version %d" % target["version_no"]
        s3_target = self.conn.execute("SELECT s3_version_id FROM versions WHERE version_id = ?", (version_id,)).fetchone()[0]
        meta = {"commit-message": quote(message), "author": quote(user["username"]), "rollback-of": s3_target}
        try:
            new_s3_id = self.storage.copy_version(f["s3_key"], s3_target, meta)
        except StorageError as exc:
            raise AppError(str(exc), 502)
        try:
            with self.conn:
                self._insert_version(file_id, new_s3_id, user["user_id"], target["size_bytes"], message,
                                     is_rollback=True, source_version_id=version_id)
        except sqlite3.Error:
            log.exception("Rollback stored but not recorded for file %s", file_id)
            raise AppError("The rollback was stored, but its record could not be saved. "
                           "Ask an administrator to run a re-sync.", 500)
        return {"file_id": file_id, "versions": self.list_versions(file_id)}

    def get_version(self, file_id: int, version_id: int):
        f = self._file(file_id)
        v = self.conn.execute("SELECT * FROM versions WHERE version_id = ? AND file_id = ?",
                              (version_id, file_id)).fetchone()
        if v is None:
            raise AppError("That version does not belong to this file.", 404)
        return f, v

    def download_link(self, file_id: int, version_id: int) -> dict:
        f, v = self.get_version(file_id, version_id)
        try:
            url = self.storage.presigned_url(f["s3_key"], v["s3_version_id"], f["file_name"])
        except StorageError as exc:
            raise AppError(str(exc), 502)
        return {"url": url, "filename": f["file_name"]}

    def content(self, file_id: int, version_id: int):
        f, v = self.get_version(file_id, version_id)
        try:
            return f["file_name"], self.storage.read_version(f["s3_key"], v["s3_version_id"])
        except StorageError as exc:
            raise AppError(str(exc), 502)

    # ---- maintenance
    def resync(self, admin: dict, team_id: Optional[int] = None, owner_id: Optional[int] = None) -> Dict[str, int]:
        """Rebuild missing version records from what storage holds.

        The commit message and author are read back from the metadata saved with every object.
        team_id: only that team's files.  owner_id: only that person's private files.  Neither: everything."""
        wanted = ("t", team_id) if team_id is not None else (("u", owner_id) if owner_id is not None else None)
        known = {(r["s3_key"], r["s3_version_id"]) for r in self.conn.execute(
            "SELECT f.s3_key, v.s3_version_id FROM versions v JOIN files f ON f.file_id = v.file_id")}
        try:
            listing = sorted(self.storage.list_object_versions(), key=lambda x: x["last_modified"])
        except StorageError as exc:
            raise AppError(str(exc), 502)
        in_scope = []
        unmapped = 0
        for v in listing:
            m = _KEY_RE.match(v["key"])
            if not m:
                unmapped += 1
                continue
            kind, ident = m.group(1), int(m.group(2))
            if wanted is None or wanted == (kind, ident):
                in_scope.append((v, kind, ident, m.group(3)))
        in_storage = {(v["key"], v["version_id"]) for v, _, _, _ in in_scope}
        added = 0
        for v, kind, ident, fname in in_scope:
            if (v["key"], v["version_id"]) in known:
                continue
            try:
                meta = self.storage.head_version(v["key"], v["version_id"])
            except StorageError as exc:
                raise AppError(str(exc), 502)
            message = unquote(meta.get("commit-message", "")) or "[recovered by re-sync: message not available]"
            author = self.conn.execute("SELECT user_id FROM users WHERE username = ?", (unquote(meta.get("author", "")),)).fetchone()
            fallback = ident if kind == "u" else admin["user_id"]
            author_id = author["user_id"] if author else fallback
            when = v["last_modified"].isoformat(timespec="milliseconds").replace("+00:00", "Z")
            with self.conn:
                f = self.conn.execute("SELECT file_id FROM files WHERE s3_key = ?", (v["key"],)).fetchone()
                file_id = f["file_id"] if f else self.conn.execute(
                    "INSERT INTO files (file_name, s3_key, created_by, created_at, team_id) VALUES (?, ?, ?, ?, ?)",
                    (fname, v["key"], author_id, when, ident if kind == "t" else None)).lastrowid
                source_id = None
                if meta.get("rollback-of"):
                    src = self.conn.execute("SELECT version_id FROM versions WHERE file_id = ? AND s3_version_id = ?",
                                            (file_id, meta["rollback-of"])).fetchone()
                    source_id = src["version_id"] if src else None
                self._insert_version(file_id, v["version_id"], author_id, v["size"], message,
                                     is_rollback=bool(meta.get("rollback-of")), source_version_id=source_id,
                                     uploaded_at=when)
            added += 1
        scope_known = {k for k in known if wanted is None or (_KEY_RE.match(k[0]) and (_KEY_RE.match(k[0]).group(1), int(_KEY_RE.match(k[0]).group(2))) == wanted)}
        return {"checked": len(in_scope), "added": added, "records_without_storage": len(scope_known - in_storage),
                "unmapped": unmapped}
