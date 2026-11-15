"""Settings, read from environment variables (or a .env file if python-dotenv is installed)."""
import os
import secrets
import warnings
from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/docvault.db"
    storage_backend: str = "local"          # "local" (demo, no AWS) or "s3"
    s3_bucket: str = ""
    aws_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None   # only for S3-compatible servers such as MinIO
    local_store_dir: str = "data/local_store"
    secret_key: str = ""
    token_hours: int = 8
    max_upload_mb: int = 200
    max_failed_attempts: int = 3
    lock_minutes: int = 15                  # a locked account opens again by itself after this time
    admin_username: str = "admin"
    admin_password: Optional[str] = None    # used once, to create the first admin
    smtp_host: Optional[str] = None         # empty = print reset codes in the backend window (demo mode)
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    reset_minutes: int = 15                 # how long an emailed code works
    reset_max_attempts: int = 5             # wrong guesses allowed per code
    reset_cooldown_seconds: int = 60        # minimum gap between two code requests
    avatar_dir: str = "data/avatars"
    invite_days: int = 7
    invite_max_uses: int = 50
    db_backup_seconds: int = 0              # above 0 (with s3 storage): back the database up to the bucket this often


def load_settings(**overrides) -> Settings:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    env = os.environ.get
    secret = env("SECRET_KEY")
    if not secret:
        warnings.warn("SECRET_KEY is not set; using a random key. Logins will be lost on every restart.")
        secret = secrets.token_hex(32)
    s = Settings(
        db_path=env("DOCVAULT_DB", "data/docvault.db"),
        storage_backend=env("STORAGE_BACKEND", "local").lower(),
        s3_bucket=env("S3_BUCKET", ""),
        aws_region=env("AWS_REGION", "us-east-1"),
        s3_endpoint_url=env("S3_ENDPOINT_URL") or None,
        local_store_dir=env("LOCAL_STORE_DIR", "data/local_store"),
        secret_key=secret,
        token_hours=int(env("TOKEN_HOURS", "8")),
        max_upload_mb=int(env("MAX_UPLOAD_MB", "200")),
        max_failed_attempts=int(env("MAX_FAILED_ATTEMPTS", "3")),
        lock_minutes=int(env("LOCK_MINUTES", "15")),
        admin_username=env("ADMIN_USERNAME", "admin"),
        admin_password=env("ADMIN_PASSWORD") or None,
        smtp_host=env("SMTP_HOST") or None,
        smtp_port=int(env("SMTP_PORT", "587")),
        smtp_user=env("SMTP_USER") or None,
        smtp_password=env("SMTP_PASSWORD") or None,
        smtp_from=env("SMTP_FROM") or None,
        reset_minutes=int(env("RESET_MINUTES", "15")),
        reset_max_attempts=int(env("RESET_MAX_ATTEMPTS", "5")),
        reset_cooldown_seconds=int(env("RESET_COOLDOWN_SECONDS", "60")),
        avatar_dir=env("AVATAR_DIR", "data/avatars"),
        invite_days=int(env("INVITE_DAYS", "7")),
        invite_max_uses=int(env("INVITE_MAX_USES", "50")),
        db_backup_seconds=int(env("DB_BACKUP_SECONDS", "0")),
    )
    return replace(s, **overrides) if overrides else s
