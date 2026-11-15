"""FastAPI backend.

Run:  uvicorn backend.main:create_app --factory --reload
Docs: http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import dbsync, services, teams
from .config import Settings, load_settings
from .db import connect, init_db
from .mailer import make_mailer
from .security import verify_token
from .services import AppError, VersionService
from .storage import make_storage

log = logging.getLogger("docvault")


class SignupIn(BaseModel):
    full_name: str
    email: str
    password: str


class VerifyIn(BaseModel):
    email: str
    code: str


class EmailIn(BaseModel):
    email: str


class LoginIn(BaseModel):
    username: str          # a username or an email address
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class ForgotIn(BaseModel):
    identifier: str


class ResetPasswordIn(BaseModel):
    identifier: str
    code: str
    new_password: str


class ProfileIn(BaseModel):
    display_name: Optional[str] = None
    theme: Optional[str] = None


class TeamIn(BaseModel):
    name: str
    description: str = ""


class TeamUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_discoverable: Optional[bool] = None


class DecideIn(BaseModel):
    approve: bool


class TokenIn(BaseModel):
    token: str


class RoleIn(BaseModel):
    role: str


class RollbackIn(BaseModel):
    version_id: int
    message: Optional[str] = None


def create_app(settings: Optional[Settings] = None, storage=None, mailer=None) -> FastAPI:
    settings = settings or load_settings()
    storage = storage or make_storage(settings)
    mailer = mailer or make_mailer(settings)
    if not log.handlers:                      # show login problems in the backend window
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s docvault: %(message)s", "%H:%M:%S"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False

    dbsync.restore_if_missing(settings, storage)      # a free host starts with an empty disk: get the backup back

    # create the tables, upgrade an older database, and (optionally) the first account
    boot = connect(settings.db_path)
    init_db(boot)
    if boot.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 and settings.admin_password:
        services.create_user(boot, settings.admin_username, settings.admin_password, "admin")
        log.warning("Created the first account '%s'.", settings.admin_username)
    boot.close()

    backup = dbsync.Backup(settings, storage) if dbsync.enabled(settings, storage) else None

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if backup is not None:                        # one last backup when the server stops
            backup.stop()

    app = FastAPI(title="DocVault", version="2.0", lifespan=lifespan)

    if backup is not None:
        backup.run_once()
        backup.start()

    @app.exception_handler(AppError)
    async def app_error_handler(request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    # ---------------------------------------------------------------- dependencies
    def get_conn():
        conn = connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def current_user_any(authorization: Optional[str] = Header(None), conn=Depends(get_conn)) -> dict:
        """A valid login, even if the user still has to choose a new password."""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AppError("Please log in.", 401)
        payload = verify_token(settings.secret_key, authorization[7:].strip())
        if payload is None:
            raise AppError("Your session has expired. Please log in again.", 401)
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (payload["uid"],)).fetchone()
        if row is None or not row["is_active"]:
            raise AppError("This account is not available.", 401)
        return {"user_id": row["user_id"], "username": row["username"], "role": row["role"],
                "must_change": bool(row["must_change_password"])}

    def current_user(user: dict = Depends(current_user_any)) -> dict:
        if user["must_change"]:
            raise AppError("Choose a new password before you continue.", 403)
        return user

    def versions_service(conn=Depends(get_conn)) -> VersionService:
        return VersionService(conn, storage, settings)

    # ---------------------------------------------------------------- general and accounts
    @app.get("/health")
    def health():
        return {"status": "ok", "storage": storage.name}

    @app.post("/signup")
    def signup(body: SignupIn, conn=Depends(get_conn)):
        return services.signup(conn, settings, mailer, body.full_name, body.email, body.password)

    @app.post("/verify-email")
    def verify_email(body: VerifyIn, conn=Depends(get_conn)):
        return services.verify_email(conn, settings, body.email, body.code)

    @app.post("/resend-verification")
    def resend_verification(body: EmailIn, conn=Depends(get_conn)):
        services.resend_verification(conn, settings, mailer, body.email)
        return {"detail": "If that address needs verifying, a new code has been sent."}

    @app.post("/login")
    def login(body: LoginIn, conn=Depends(get_conn)):
        return services.authenticate(conn, settings, body.username, body.password)

    @app.post("/change-password")
    def change_password(body: ChangePasswordIn, user: dict = Depends(current_user_any), conn=Depends(get_conn)):
        services.change_password(conn, user["user_id"], body.current_password, body.new_password)
        return {"ok": True}

    @app.post("/forgot-password")
    def forgot_password(body: ForgotIn, conn=Depends(get_conn)):
        services.request_reset(conn, settings, mailer, body.identifier)
        # the same answer whether or not the account exists
        return {"detail": "If that account exists and has an email address, a code has been sent to it.",
                "demo": getattr(mailer, "name", "") == "console"}

    @app.post("/reset-password")
    def reset_password(body: ResetPasswordIn, conn=Depends(get_conn)):
        services.reset_password(conn, settings, body.identifier, body.code, body.new_password)
        return {"ok": True}

    # ---------------------------------------------------------------- profile
    @app.get("/me")
    def me(user: dict = Depends(current_user_any), conn=Depends(get_conn)):
        prof = services.get_profile(conn, user["user_id"])
        prof["must_change"] = user["must_change"]
        return prof

    @app.patch("/me")
    def update_me(body: ProfileIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return services.update_profile(conn, user["user_id"], body.display_name, body.theme)

    @app.post("/me/avatar")
    def upload_avatar(file: UploadFile = File(...), user: dict = Depends(current_user), conn=Depends(get_conn)):
        services.save_avatar(conn, settings, user["user_id"], file.file.read(services.MAX_AVATAR_BYTES + 1))
        return {"ok": True}

    @app.delete("/me/avatar")
    def delete_avatar(user: dict = Depends(current_user), conn=Depends(get_conn)):
        services.remove_avatar(conn, settings, user["user_id"])
        return {"ok": True}

    @app.get("/users/{user_id}/avatar")
    def avatar(user_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return Response(content=services.avatar_bytes(conn, settings, user_id), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=60"})

    # ---------------------------------------------------------------- teams
    @app.get("/teams")
    def my_teams(user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.my_teams(conn, user["user_id"])

    @app.post("/teams")
    def create_team(body: TeamIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.create_team(conn, user, body.name, body.description)

    @app.get("/teams/search")
    def search_teams(q: str = "", user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.search_teams(conn, user, q)

    @app.patch("/teams/{team_id}")
    def update_team(team_id: int, body: TeamUpdateIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.update_team(conn, user, team_id, body.name, body.description, body.is_discoverable)

    @app.get("/teams/{team_id}/members")
    def team_members(team_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.members(conn, user, team_id)

    @app.post("/teams/{team_id}/members/{member_id}/role")
    def set_role(team_id: int, member_id: int, body: RoleIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
        teams.set_role(conn, user, team_id, member_id, body.role)
        return {"ok": True}

    @app.delete("/teams/{team_id}/members/{member_id}")
    def remove_member(team_id: int, member_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        teams.remove_member(conn, user, team_id, member_id)
        return {"ok": True}

    @app.post("/teams/{team_id}/join-requests")
    def request_join(team_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        teams.request_join(conn, user, team_id)
        return {"ok": True}

    @app.get("/teams/{team_id}/join-requests")
    def join_requests(team_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.pending_requests(conn, user, team_id)

    @app.post("/join-requests/{request_id}/decide")
    def decide(request_id: int, body: DecideIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
        teams.decide_request(conn, user, request_id, body.approve)
        return {"ok": True}

    @app.post("/teams/{team_id}/invites")
    def create_invite(team_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.create_invite(conn, settings, user, team_id)

    @app.get("/teams/{team_id}/invites")
    def list_invites(team_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.list_invites(conn, user, team_id)

    @app.delete("/invites/{invite_id}")
    def revoke_invite(invite_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
        teams.revoke_invite(conn, user, invite_id)
        return {"ok": True}

    @app.post("/invites/accept")
    def accept_invite(body: TokenIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
        return teams.accept_invite(conn, settings, user, body.token)

    # ---------------------------------------------------------------- files (team_id empty = your private space)
    @app.post("/upload")
    def upload(file: UploadFile = File(...), message: str = Form(...), team_id: Optional[int] = Form(None),
               user: dict = Depends(current_user), svc: VersionService = Depends(versions_service)):
        limit = settings.max_upload_mb * 1024 * 1024
        data = file.file.read(limit + 1)
        return svc.upload(user, file.filename, data, message, team_id)

    @app.get("/files")
    def files(team_id: Optional[int] = None, user: dict = Depends(current_user),
              conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        services.require_workspace(conn, user["user_id"], team_id)
        return svc.list_files(team_id=team_id, owner_id=None if team_id is not None else user["user_id"])

    @app.get("/history")
    def history(team_id: Optional[int] = None, user: dict = Depends(current_user),
                conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        services.require_workspace(conn, user["user_id"], team_id)
        return svc.history_all(team_id=team_id, owner_id=None if team_id is not None else user["user_id"])

    @app.get("/files/{file_id}/versions")
    def versions(file_id: int, user: dict = Depends(current_user),
                 conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        services.file_access(conn, user["user_id"], file_id)
        return svc.list_versions(file_id)

    @app.get("/files/{file_id}/download/{version_id}")
    def download(file_id: int, version_id: int, user: dict = Depends(current_user),
                 conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        services.file_access(conn, user["user_id"], file_id)
        return svc.download_link(file_id, version_id)

    @app.get("/files/{file_id}/content/{version_id}")
    def content(file_id: int, version_id: int, user: dict = Depends(current_user),
                conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        services.file_access(conn, user["user_id"], file_id)
        name, data = svc.content(file_id, version_id)
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})

    @app.post("/files/{file_id}/rollback")
    def rollback(file_id: int, body: RollbackIn, user: dict = Depends(current_user),
                 conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        services.file_access(conn, user["user_id"], file_id)
        return svc.rollback(user, file_id, body.version_id, body.message)

    @app.post("/resync")
    def resync(team_id: Optional[int] = None, user: dict = Depends(current_user),
               conn=Depends(get_conn), svc: VersionService = Depends(versions_service)):
        if team_id is not None:
            teams.require_owner(conn, user["user_id"], team_id)
        return svc.resync(user, team_id=team_id, owner_id=None if team_id is not None else user["user_id"])

    return app
