"""SQLite metadata database (the four tables from Figure 3.8)."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    email           TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    display_name    TEXT,
    theme           TEXT NOT NULL DEFAULT 'light',
    has_avatar      INTEGER NOT NULL DEFAULT 0,
    email_verified  INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    file_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name  TEXT NOT NULL,
    s3_key     TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    team_id    INTEGER REFERENCES teams(team_id),
    folder     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS folders (
    folder_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    scope      TEXT NOT NULL,
    path       TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    UNIQUE (scope, path)
);
CREATE TABLE IF NOT EXISTS versions (
    version_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id           INTEGER NOT NULL REFERENCES files(file_id),
    s3_version_id     TEXT NOT NULL,
    uploaded_by       INTEGER NOT NULL REFERENCES users(user_id),
    uploaded_at       TEXT NOT NULL,
    size_bytes        INTEGER,
    commit_message    TEXT NOT NULL,
    is_rollback       INTEGER NOT NULL DEFAULT 0,
    source_version_id INTEGER REFERENCES versions(version_id),
    UNIQUE (file_id, s3_version_id)
);
CREATE TABLE IF NOT EXISTS login_log (
    log_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    logged_at TEXT NOT NULL,
    success   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS password_resets (
    reset_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    code_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    used       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS teams (
    team_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    is_discoverable INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER NOT NULL REFERENCES users(user_id),
    created_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_name ON teams(lower(name));
CREATE TABLE IF NOT EXISTS team_members (
    team_id   INTEGER NOT NULL REFERENCES teams(team_id),
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    role      TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (team_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_invites (
    invite_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL REFERENCES teams(team_id),
    token_hash TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    max_uses   INTEGER NOT NULL,
    uses       INTEGER NOT NULL DEFAULT 0,
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS join_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL REFERENCES teams(team_id),
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'declined')),
    created_at TEXT NOT NULL,
    decided_by INTEGER REFERENCES users(user_id),
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS email_verifications (
    verify_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    code_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    used       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_versions_file ON versions(file_id, uploaded_at, version_id);
"""


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utcnow() -> str:
    return _fmt(datetime.now(timezone.utc))


def utc_in(seconds: int) -> str:
    return _fmt(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def connect(path: str) -> sqlite3.Connection:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # upgrade a database created by an earlier version
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "must_change_password" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    for name, ddl in (("display_name", "TEXT"), ("theme", "TEXT NOT NULL DEFAULT 'light'"),
                      ("has_avatar", "INTEGER NOT NULL DEFAULT 0"), ("email_verified", "INTEGER NOT NULL DEFAULT 1")):
        if name not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN %s %s" % (name, ddl))
    fcols = {r["name"] for r in conn.execute("PRAGMA table_info(files)")}
    if "team_id" not in fcols:
        conn.execute("ALTER TABLE files ADD COLUMN team_id INTEGER REFERENCES teams(team_id)")
    if "folder" not in fcols:
        conn.execute("ALTER TABLE files ADD COLUMN folder TEXT NOT NULL DEFAULT ''")
    # themes that no longer exist (for example the very first coloured ones) fall back to the default theme
    conn.execute("UPDATE users SET theme = 'light' WHERE theme NOT IN ('light', 'dark', 'paper', 'silver', 'graphite', 'sky', 'mint', 'violet', 'amber', 'blush', 'indigo', 'aurora')")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL")
    conn.commit()
    _migrate_legacy_files(conn)


def _migrate_legacy_files(conn: sqlite3.Connection) -> None:
    """Files from the first version belonged to everyone. Put them in a 'Default team' with all existing users."""
    legacy = "team_id IS NULL AND s3_key NOT GLOB 'u[0-9]*/*'"
    if not conn.execute("SELECT COUNT(*) FROM files WHERE " + legacy).fetchone()[0]:
        return
    team = conn.execute("SELECT team_id FROM teams WHERE lower(name) = 'default team'").fetchone()
    if team is None:
        owner = conn.execute("SELECT user_id FROM users ORDER BY (role = 'admin') DESC, user_id LIMIT 1").fetchone()
        now = utcnow()
        tid = conn.execute("INSERT INTO teams (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
                           ("Default team", "Created automatically for the files that existed before teams.",
                            owner["user_id"], now)).lastrowid
        for u in conn.execute("SELECT user_id FROM users").fetchall():
            conn.execute("INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
                         (tid, u["user_id"], "owner" if u["user_id"] == owner["user_id"] else "member", now))
    else:
        tid = team["team_id"]
    conn.execute("UPDATE files SET team_id = ? WHERE " + legacy, (tid,))
    conn.commit()
