"""DocVault interface (Streamlit).

Run:  streamlit run frontend/app.py        (the backend must be running first, see README)
"""
import base64
import io
import os
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import requests
import streamlit as st

import editors
import embedded
from theme import DEFAULT_THEME, THEMES, brand_html, css, initials, logo_html

embedded.start_if_enabled()          # on single-program hosts (Streamlit Community Cloud) the API runs in this process
API = os.environ.get("DOCVAULT_API", "http://localhost:8000").rstrip("/")
APP_URL = os.environ.get("DOCVAULT_APP_URL", "http://localhost:8501").rstrip("/")
TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "Africa/Lagos"))

st.set_page_config(page_title="DocVault", layout="wide", initial_sidebar_state="collapsed")
S = st.session_state
for _k, _v in (("auth_view", "login"), ("page", "files"), ("team_id", None), ("theme", DEFAULT_THEME), ("teams", [])):
    S.setdefault(_k, _v)


# ----------------------------------------------------------------- helpers
def fmt_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    return dt.strftime("%d %b %Y, %H:%M")


def fmt_size(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024


def file_icon(name: str) -> str:
    """A short text label for the file type (no pictures)."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for label, exts in (("PDF", ("pdf",)), ("DOC", ("doc", "docx", "odt", "rtf", "txt", "md")),
                        ("XLS", ("xls", "xlsx", "csv", "ods", "tsv")), ("PPT", ("ppt", "pptx", "odp")),
                        ("IMG", ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp")), ("ZIP", ("zip", "rar", "7z")),
                        ("VID", ("mp4", "webm", "mov", "m4v", "ogv")), ("AUD", ("mp3", "wav", "ogg", "m4a", "flac", "aac"))):
        if ext in exts:
            return label
    return "FILE"


def api(method: str, path: str, **kwargs) -> requests.Response:
    headers = {}
    if S.get("token"):
        headers["Authorization"] = "Bearer " + S["token"]
    try:
        resp = requests.request(method, API + path, headers=headers, timeout=120, **kwargs)
    except requests.RequestException:
        st.error("Cannot reach the server at %s. Is the backend running?" % API)
        st.stop()
    if resp.status_code == 401 and S.get("token"):
        logout(message="Your session has ended. Please log in again.")
    return resp


def problem(resp: requests.Response) -> str:
    try:
        detail = resp.json().get("detail", "Something went wrong.")
        return detail if isinstance(detail, str) else "Please check what you typed and try again."
    except ValueError:
        return "Something went wrong (%s)." % resp.status_code


def logout(message: str = None):
    theme = S.get("theme", DEFAULT_THEME)
    S.clear()
    S["theme"] = theme
    if message:
        S["flash"] = message
    st.rerun()


def goto(page: str):
    S["page"] = page
    S.pop("open_file", None)
    S.pop("manage_team", None)


def switch_workspace(team_id):
    """Used as a button callback: runs before the page is drawn, so it may change widget state."""
    S["team_id"] = team_id
    S["ws_select"] = next((t["name"] for t in S["teams"] if t["team_id"] == team_id), "My files")
    S["page"] = "files"
    S.pop("open_file", None)


def ws_params():
    return {"team_id": S["team_id"]} if S["team_id"] is not None else {}


def ws_name() -> str:
    return next((t["name"] for t in S["teams"] if t["team_id"] == S["team_id"]), "My files")


def small_avatar_uri(data: bytes) -> str:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB").resize((96, 96))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
    except Exception:
        pass
    return "data:image/png;base64," + base64.b64encode(data).decode()


def load_session():
    """After login: profile, theme, avatar, and teams."""
    r = api("GET", "/me")
    if r.ok:
        S["profile"] = r.json()
        S["theme"] = S["profile"]["theme"]
        S["avatar_uri"] = None
        S["avatar_raw"] = None
        if S["profile"]["has_avatar"]:
            a = api("GET", "/users/%d/avatar" % S["profile"]["user_id"])
            if a.ok:
                S["avatar_raw"] = a.content
                S["avatar_uri"] = small_avatar_uri(a.content)
    refresh_teams()


def refresh_teams():
    r = api("GET", "/teams")
    S["teams"] = r.json() if r.ok else []
    if S["team_id"] is not None and S["team_id"] not in [t["team_id"] for t in S["teams"]]:
        S["team_id"] = None
        S["ws_select"] = "My files"


def complete_login(data: dict):
    S["token"] = data["token"]
    S["user"] = data["user"]
    S["page"] = "files"
    if not data["user"].get("must_change_password"):
        load_session()
        accept_pending_invite()
    st.rerun()


def accept_pending_invite():
    token = S.pop("invite_token", None)
    if not token:
        return
    r = api("POST", "/invites/accept", json={"token": token})
    if r.ok:
        refresh_teams()
        team = r.json()
        S["team_id"] = team["team_id"]
        S["ws_select"] = team["name"]
        S["flash"] = "You joined the team \u201c%s\u201d." % team["name"]
    else:
        S["flash"] = problem(r)


def inject_theme():
    prof = S.get("profile") or {}
    name = prof.get("display_name") or S.get("user", {}).get("display_name", "?")
    st.markdown(css(S["theme"], S.get("avatar_uri"), name), unsafe_allow_html=True)
    # remove the "Press Enter to submit form" hint wherever Streamlit draws it (works whatever its internal name is)
    import streamlit.components.v1 as components
    components.html(r"""<script>
    (function(){var d=window.parent.document;
    function clean(){d.querySelectorAll('div,span,small,p').forEach(function(e){
      if(e.children.length===0 && /^\s*Press (Enter|Ctrl\+Enter|Cmd\+Enter)[^]{0,40}$/i.test(e.textContent||'')){e.style.display='none';}});}
    clean(); new window.parent.MutationObserver(clean).observe(d.body,{childList:true,subtree:true});})();
    </script>""", height=0)


def flash():
    msg = S.pop("flash", None)
    if msg:
        st.toast(msg)


# ----------------------------------------------------------------- sign in, sign up, verify, forgot password
def auth_screen():
    inject_theme()
    flash()
    token = st.query_params.get("invite")
    if token:
        S["invite_token"] = token
        st.query_params.clear()
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        st.markdown(brand_html(), unsafe_allow_html=True)
        if S.get("invite_token"):
            st.info("You were invited to join a team. Log in or create an account, and you will be added automatically.")
        with st.container(key="card_auth"):
            {"login": login_view, "signup": signup_view, "verify": verify_view, "forgot": forgot_view}[S["auth_view"]]()


def set_view(view: str):
    S["auth_view"] = view


def tinput(label: str, **kw):
    """st.text_input with browser autofill hints (ignored by older Streamlit versions)."""
    try:
        return st.text_input(label, **kw)
    except TypeError:
        kw.pop("autocomplete", None)
        return st.text_input(label, **kw)


def login_view():
    st.subheader("Welcome back")
    with st.form("login_form"):      # one submit per click or Enter, and the browser's autofill is included
        ident = tinput("Email or username", key="li_ident", autocomplete="username")
        pw = tinput("Password", type="password", key="li_pw", autocomplete="current-password")
        go = st.form_submit_button("Log in", type="primary", use_container_width=True)
    with st.container(key="linkrow_forgot"):
        st.button("Forgot password?", key="to_forgot", on_click=set_view, args=("forgot",))
    if go:
        if not ident.strip() or not pw:
            st.error("Enter your email or username and your password.")
        else:
            r = api("POST", "/login", json={"username": ident.strip(), "password": pw})
            if r.ok:
                complete_login(r.json())
            else:
                st.error(problem(r))
                if r.status_code == 403 and "verify" in problem(r).lower():
                    S["verify_email"] = ident.strip() if "@" in ident else ""
                    st.button("Enter my verification code", key="to_verify", on_click=set_view, args=("verify",))
    st.markdown('<div class="dv-or">New to DocVault?</div>', unsafe_allow_html=True)
    st.button("Create an account", key="to_signup", use_container_width=True, on_click=set_view, args=("signup",))


def signup_view():
    st.subheader("Create your account")
    with st.form("signup_form"):         # a form sends every box together when you click, so nothing is lost
        name = st.text_input("Full name", key="su_name")
        email = st.text_input("Email address", key="su_email", placeholder="you@gmail.com")
        pw = tinput("Password (8+ characters)", type="password", key="su_pw", autocomplete="new-password")
        pw2 = tinput("Repeat the password", type="password", key="su_pw2", autocomplete="new-password")
        go = st.form_submit_button("Create account", type="primary", use_container_width=True)
    if go:
        if not name.strip() or not email.strip():
            st.error("Enter your name and your email address.")
        elif pw != pw2:
            st.error("The two passwords do not match.")
        else:
            r = api("POST", "/signup", json={"full_name": name, "email": email, "password": pw})
            if r.ok:
                S["verify_email"] = email.strip().lower()
                S["auth_view"] = "verify"
                S["flash"] = r.json()["detail"]
                st.rerun()
            else:
                st.error(problem(r))
    with st.container(key="linkrow_back_signup"):
        st.button("I already have an account", key="su_back", on_click=set_view, args=("login",))


def verify_view():
    st.subheader("Check your email")
    st.caption("Enter the 6-digit code we sent to this address. (In demo mode the code is shown in the backend window.)")
    with st.form("verify_form"):
        email = st.text_input("Email address", value=S.get("verify_email", ""), key="vf_email")
        code = st.text_input("Verification code", key="vf_code", max_chars=6)
        go = st.form_submit_button("Verify and continue", type="primary", use_container_width=True)
        resend = st.form_submit_button("Send a new code", use_container_width=True)
    if go:
        r = api("POST", "/verify-email", json={"email": email.strip(), "code": code.strip()})
        if r.ok:
            complete_login(r.json())
        else:
            st.error(problem(r))
    elif resend:
        r = api("POST", "/resend-verification", json={"email": email.strip()})
        st.info(r.json()["detail"] if r.ok else problem(r))
    with st.container(key="linkrow_back_verify"):
        st.button("Back to log in", key="vf_back", on_click=set_view, args=("login",))


def forgot_view():
    st.subheader("Reset your password")
    with st.form("forgot_form"):
        ident = tinput("Email or username", key="fp_ident", autocomplete="username")
        send = st.form_submit_button("Send me a code", type="primary", use_container_width=True)
    if send:
        r = api("POST", "/forgot-password", json={"identifier": ident.strip()})
        if r.ok:
            S["fp_sent"] = True
            S["fp_who"] = ident.strip()
            st.info(r.json()["detail"])
            if r.json().get("demo"):
                st.warning("Demo mode: no email is sent. The 6-digit code is printed in the backend window (the one running uvicorn).")
        else:
            st.error(problem(r))
    if S.get("fp_sent"):
        with st.form("reset_form"):
            code = st.text_input("6-digit code", key="fp_code", max_chars=6)
            pw1 = tinput("New password (8+ characters)", type="password", key="fp_pw1", autocomplete="new-password")
            pw2 = tinput("Repeat the new password", type="password", key="fp_pw2", autocomplete="new-password")
            setpw = st.form_submit_button("Set new password", type="primary", use_container_width=True)
        if setpw:
            if pw1 != pw2:
                st.error("The two passwords do not match.")
            else:
                r = api("POST", "/reset-password", json={"identifier": S.get("fp_who", ident), "code": code.strip(),
                                                         "new_password": pw1})
                if r.ok:
                    S["fp_sent"] = False
                    S["auth_view"] = "login"
                    S["flash"] = "Password changed. You can log in now."
                    st.rerun()
                else:
                    st.error(problem(r))
    with st.container(key="linkrow_back_forgot"):
        st.button("Back to log in", key="fp_back", on_click=set_view, args=("login",))


# ----------------------------------------------------------------- top bar
NAV = (("files", "Files"), ("upload", "Upload"), ("teams", "Teams"))


def topbar():
    prof = S["profile"]
    with st.container(key="topbar"):
        cols = st.columns([2.0, 1.25, 1.25, 1.25, 0.5, 2.3, 0.6], vertical_alignment="center")
        cols[0].markdown(logo_html(34, 22), unsafe_allow_html=True)
        for i, (key, label) in enumerate(NAV):
            with cols[1 + i]:
                with st.container(key=("navon_" if S["page"] == key else "navoff_") + key):
                    st.button(label, key="nav_" + key, on_click=goto, args=(key,), use_container_width=True)
        opts = ["My files"] + [t["name"] for t in S["teams"]]
        if S.get("ws_select") not in opts:
            S["ws_select"] = ws_name()
        choice = cols[5].selectbox("Workspace", opts, key="ws_select", label_visibility="collapsed")
        wanted = next((t["team_id"] for t in S["teams"] if t["name"] == choice), None)
        if wanted != S["team_id"]:
            S["team_id"] = wanted
            S.pop("open_file", None)
            st.rerun()
        with cols[6]:
            with st.container(key="avatar"):
                with st.popover("Account", use_container_width=False):
                    st.markdown("**%s**" % escape(prof["display_name"]))
                    st.caption(prof.get("email") or "@" + prof["username"])
                    st.button("Profile", key="pm_profile", use_container_width=True, on_click=goto, args=("profile",))
                    st.button("Settings", key="pm_settings", use_container_width=True, on_click=goto, args=("settings",))
                    if st.button("Log out", key="pm_logout", use_container_width=True):
                        logout()


# ----------------------------------------------------------------- files and the Time Machine
def open_file(f: dict):
    S["open_file"] = f
    S.pop("edit_mode", None)
    S.pop("dl", None)
    S.pop("rb", None)


def close_file():
    S.pop("open_file", None)
    S.pop("edit_mode", None)


def files_page():
    if S.get("open_file"):
        return timeline_view(S["open_file"])
    team = next((t for t in S["teams"] if t["team_id"] == S["team_id"]), None)
    st.markdown("<div class='dv-h'>%s</div>" % escape(ws_name()), unsafe_allow_html=True)
    st.caption(team["description"] or "%d member%s" % (team["member_count"], "" if team["member_count"] == 1 else "s")
               if team else "Only you can see the files in this space.")
    r = api("GET", "/files", params=ws_params())
    if not r.ok:
        st.error(problem(r))
        return
    files = r.json()
    if not files:
        st.info("Nothing here yet. Add the first file from the **Upload** tab.")
        return
    q = st.text_input("Search", placeholder="Search files by name", label_visibility="collapsed", key="file_q").strip().lower()
    shown = [f for f in files if q in f["file_name"].lower()]
    if not shown:
        st.caption("No file matches \u201c%s\u201d." % escape(q))
    for f in shown:
        with st.container(key="card_file_%d" % f["file_id"]):
            c1, c2, c3 = st.columns([5, 3.2, 1.1], vertical_alignment="center")
            c1.markdown("<div class='dv-file'><div class='dv-ico'><span style='font-size:.75rem;font-weight:700;letter-spacing:.04em'>%s</span></div><div><b>%s</b><div class='dv-muted'>%s</div></div></div>"
                        % (file_icon(f["file_name"]), escape(f["file_name"]), escape(f["last_message"])), unsafe_allow_html=True)
            c2.markdown("<div class='dv-muted'>%d version%s \u00B7 %s<br>%s \u00B7 %s</div>" % (
                f["version_count"], "" if f["version_count"] == 1 else "s", escape(f["last_author"]),
                fmt_time(f["last_modified"]), fmt_size(f["size_bytes"])), unsafe_allow_html=True)
            c3.button("Open", key="open_%d" % f["file_id"], on_click=open_file, args=(f,), use_container_width=True)
    with st.expander("Recent activity"):
        h = api("GET", "/history", params=ws_params())
        for row in (h.json()[:12] if h.ok else []):
            st.markdown("%s **%s** \u2014 %s \u00B7 *%s* \u00B7 %s" % (
                "Rollback by" if row["is_rollback"] else "Upload by", escape(row["author_name"]), escape(row["file_name"]),
                escape(row["commit_message"]), fmt_time(row["uploaded_at"])))


def start_editing(f: dict, base_version_id: int, view_only: bool):
    S["edit_mode"] = {"file": f, "base": base_version_id, "view_only": view_only}
    S.pop("dl", None)
    S.pop("rb", None)


def stop_editing():
    S.pop("edit_mode", None)


def editor_page(em: dict):
    f, base, view_only = em["file"], em["base"], em["view_only"]
    name = f["file_name"]
    st.button("\u2190 Back to versions", key="back_versions", on_click=stop_editing)
    st.markdown("<div class='dv-h'>%s</div>" % escape(name), unsafe_allow_html=True)
    cache = S.get("edit_data")
    if not cache or cache[:2] != (f["file_id"], base):
        resp = api("GET", "/files/%d/content/%d" % (f["file_id"], base))
        if not resp.ok:
            st.error(problem(resp))
            return
        cache = S["edit_data"] = (f["file_id"], base, resp.content)
    data = cache[2]
    key = "ed%d_%d" % (f["file_id"], base)
    if view_only:
        st.caption("Viewing only. This kind of file cannot be edited in the browser.")
        editors.view_file(data, name, key)
        return
    st.caption("Edit the file here, then save it as a new version with a commit message.")
    new_data = editors.edit_file(data, name, key)
    st.divider()
    msg = st.text_area("Commit message (required)", max_chars=500, placeholder="What did you change, and why?",
                       key=key + "_msg")
    vr = api("GET", "/files/%d/versions" % f["file_id"])
    latest = vr.json()[-1] if vr.ok and vr.json() else None
    moved_on = latest is not None and latest["version_id"] != base
    force = True
    if moved_on:
        st.warning("Someone saved a newer version (version %d by %s) while you were editing. Saving now adds your "
                   "edit on top of it, and their changes will not be in your file." % (latest["version_no"], latest["author"]))
        force = st.checkbox("Save my version anyway", key=key + "_force")
    c1, c2, _ = st.columns([1.4, 1, 3])
    if c1.button("Save as new version", type="primary", key=key + "_save"):
        if new_data is None:
            st.error("You have not changed anything yet.")
        elif not msg.strip():
            st.error("Enter a commit message.")
        elif not force:
            st.error("Tick \u201cSave my version anyway\u201d, or go back and reopen the newest version.")
        else:
            form = {"message": msg}
            if S["team_id"] is not None:
                form["team_id"] = str(S["team_id"])
            resp = api("POST", "/upload", files={"file": (name, new_data)}, data=form)
            if resp.ok:
                S.pop("edit_mode", None)
                S.pop("edit_data", None)
                S["flash"] = "Saved. %s now has %d versions." % (name, len(resp.json()["versions"]))
                st.rerun()
            else:
                st.error(problem(resp))
    if c2.button("Discard", key=key + "_discard"):
        S.pop("edit_mode", None)
        st.rerun()


def timeline_view(f: dict):
    if S.get("edit_mode") and S["edit_mode"]["file"]["file_id"] == f["file_id"]:
        return editor_page(S["edit_mode"])
    st.button("\u2190 Back to files", key="back_files", on_click=close_file)
    st.markdown("<div class='dv-h'>%s</div>" % escape(f["file_name"]), unsafe_allow_html=True)
    st.caption("Time Machine \u2014 every version, who made it, and why.")
    r = api("GET", "/files/%d/versions" % f["file_id"])
    if not r.ok:
        st.error(problem(r))
        return
    versions = r.json()
    if versions and (editors.can_edit(f["file_name"]) or editors.can_view(f["file_name"])):
        cur = versions[-1]
        label = "Edit in browser" if editors.can_edit(f["file_name"]) else "View"
        if st.button(label, key="edit_btn", type="primary"):
            start_editing(f, cur["version_id"], not editors.can_edit(f["file_name"]))
            st.rerun()
    for v in reversed(versions):                      # newest first
        with st.container(key="card_ver_%d" % v["version_id"]):
            left, right = st.columns([4.2, 1.8], vertical_alignment="center")
            badge = "<span class='dv-badge dv-badge-now'>current</span>" if v["is_current"] else ""
            if v["is_rollback"]:
                badge += "<span class='dv-badge'>rollback to v%s</span>" % v["source_version_no"]
            left.markdown("<b>Version %d</b> %s<br>%s<div class='dv-muted'>%s \u00B7 %s \u00B7 %s</div>" % (
                v["version_no"], badge, escape(v["commit_message"]), escape(v["author"]), fmt_time(v["uploaded_at"]),
                fmt_size(v["size_bytes"])), unsafe_allow_html=True)
            if right.button("Download", key="dl%d" % v["version_id"], use_container_width=True):
                S["dl"] = (f["file_id"], v["version_id"], v["version_no"])
                S.pop("rb", None)
            if not v["is_current"] and right.button("Roll back to this", key="rb%d" % v["version_id"], use_container_width=True):
                S["rb"] = (f["file_id"], v["version_id"], v["version_no"])
                S.pop("dl", None)

    dl = S.get("dl")
    if dl and dl[0] == f["file_id"]:
        resp = api("GET", "/files/%d/download/%d" % (dl[0], dl[1]))
        if not resp.ok:
            st.error(problem(resp))
        else:
            info = resp.json()
            if info["url"]:
                st.link_button("Get version %d (the link works for 5 minutes)" % dl[2], info["url"])
            else:
                data = api("GET", "/files/%d/content/%d" % (dl[0], dl[1]))
                if data.ok:
                    st.download_button("Save version %d" % dl[2], data.content, file_name=info["filename"], type="primary")
                else:
                    st.error(problem(data))

    rb = S.get("rb")
    if rb and rb[0] == f["file_id"]:
        st.warning("Roll back to version %d? A new version is added; nothing is deleted." % rb[2])
        msg = st.text_input("Commit message", value="Rollback to version %d" % rb[2], max_chars=500, key="rb_msg")
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Confirm rollback", type="primary", key="rb_ok"):
            resp = api("POST", "/files/%d/rollback" % rb[0], json={"version_id": rb[1], "message": msg})
            if resp.ok:
                S.pop("rb", None)
                S["flash"] = "Done. Version %d is now the newest version." % len(resp.json()["versions"])
                st.rerun()
            else:
                st.error(problem(resp))
        if c2.button("Cancel", key="rb_cancel"):
            S.pop("rb", None)
            st.rerun()


# ----------------------------------------------------------------- upload
def upload_page():
    st.markdown("<div class='dv-h'>Upload</div>", unsafe_allow_html=True)
    st.caption("Uploading to **%s**. A file with a name that already exists there gets a **new version**." % ws_name())
    with st.expander("Create a new blank document"):
        n1, n2 = st.columns([2, 3])
        new_type = n1.selectbox("Type", list(editors.NEW_TYPES), key="new_type")
        new_name = n2.text_input("File name (without the ending)", key="new_name", max_chars=100)
        if st.button("Create and open", key="new_btn"):
            ext = editors.NEW_TYPES[new_type]
            base = new_name.strip()
            if not base:
                st.error("Enter a file name.")
            else:
                fname = base if base.lower().endswith("." + ext) else "%s.%s" % (base, ext)
                form = {"message": "Create %s" % fname}
                if S["team_id"] is not None:
                    form["team_id"] = str(S["team_id"])
                resp = api("POST", "/upload", files={"file": (fname, editors.blank_file(ext))}, data=form)
                if resp.ok:
                    fid = resp.json()["file_id"]
                    vers = resp.json()["versions"]
                    S["page"] = "files"
                    open_file({"file_id": fid, "file_name": fname})
                    start_editing(S["open_file"], vers[-1]["version_id"], False)
                    st.rerun()
                else:
                    st.error(problem(resp))
    up = st.file_uploader("Choose a file", key="up_file")
    message = st.text_area("Commit message (required)", max_chars=500, placeholder="What did you change, and why?", key="up_msg")
    if st.button("Upload", type="primary", key="up_btn"):
        if up is None:
            st.error("Choose a file first.")
        elif not message.strip():
            st.error("Enter a commit message.")
        else:
            data = {"message": message}
            if S["team_id"] is not None:
                data["team_id"] = str(S["team_id"])
            resp = api("POST", "/upload", files={"file": (up.name, up.getvalue())}, data=data)
            if resp.ok:
                n = len(resp.json()["versions"])
                st.success("Saved. %s now has %d version%s." % (up.name, n, "" if n == 1 else "s"))
                st.balloons()
            else:
                st.error(problem(resp))


# ----------------------------------------------------------------- teams
def teams_page():
    st.markdown("<div class='dv-h'>Teams</div>", unsafe_allow_html=True)
    st.caption("Work together on shared files. Your personal files stay private.")
    tab_mine, tab_find, tab_new = st.tabs(["My teams", "Find a team", "Create a team"])
    with tab_mine:
        my_teams_tab()
    with tab_find:
        find_team_tab()
    with tab_new:
        create_team_tab()


def my_teams_tab():
    if not S["teams"]:
        st.info("You are not in a team yet. Find one to join, ask for an invite link, or create your own.")
    for t in S["teams"]:
        with st.container(key="card_team_%d" % t["team_id"]):
            c1, c2, c3, c4 = st.columns([4, 1.4, 1.2, 1.3], vertical_alignment="center")
            c1.markdown("<b>%s</b><span class='dv-badge'>%s</span><div class='dv-muted'>%s \u00B7 %d member%s</div>" % (
                escape(t["name"]), t["role"], escape(t["description"] or "No description"), t["member_count"],
                "" if t["member_count"] == 1 else "s"), unsafe_allow_html=True)
            c2.button("Open files", key="tf_%d" % t["team_id"], on_click=switch_workspace, args=(t["team_id"],), use_container_width=True)
            if t["role"] == "owner":
                if c3.button("Manage", key="tm_%d" % t["team_id"], use_container_width=True):
                    S["manage_team"] = None if S.get("manage_team") == t["team_id"] else t["team_id"]
            else:
                if c3.button("Leave", key="tl_%d" % t["team_id"], use_container_width=True):
                    r = api("DELETE", "/teams/%d/members/%d" % (t["team_id"], S["profile"]["user_id"]))
                    if r.ok:
                        refresh_teams()
                        S["flash"] = "You left %s." % t["name"]
                        st.rerun()
                    else:
                        st.error(problem(r))
        if S.get("manage_team") == t["team_id"]:
            manage_team(t)


def manage_team(t: dict):
    tid = t["team_id"]
    with st.container(key="card_manage_%d" % tid):
        st.markdown("#### Manage %s" % escape(t["name"]))
        # --- join requests
        reqs = api("GET", "/teams/%d/join-requests" % tid)
        pending = reqs.json() if reqs.ok else []
        st.markdown("**Join requests** (%d)" % len(pending))
        for p in pending:
            c1, c2, c3 = st.columns([4, 1, 1], vertical_alignment="center")
            c1.markdown("%s \u2014 %s" % (escape(p["display_name"]), escape(p["email"] or "@" + p["username"])))
            for col, ok, label in ((c2, True, "Approve"), (c3, False, "Decline")):
                if col.button(label, key="%s_%d" % ("ap" if ok else "de", p["request_id"]), use_container_width=True):
                    api("POST", "/join-requests/%d/decide" % p["request_id"], json={"approve": ok})
                    refresh_teams()
                    st.rerun()
        # --- invite links
        st.markdown("**Invite link**")
        st.caption("Anyone with the link can join after logging in. Links stop working after 7 days, and you can cancel them.")
        if st.button("Create an invite link", key="inv_new_%d" % tid):
            r = api("POST", "/teams/%d/invites" % tid)
            if r.ok:
                S["new_invite"] = (tid, "%s/?invite=%s" % (APP_URL, r.json()["token"]))
            else:
                st.error(problem(r))
        if S.get("new_invite") and S["new_invite"][0] == tid:
            st.success("Copy this link now. For safety it is shown only once.")
            st.code(S["new_invite"][1], language=None)
        invites = api("GET", "/teams/%d/invites" % tid)
        for inv in (invites.json() if invites.ok else []):
            c1, c2 = st.columns([5, 1.2], vertical_alignment="center")
            c1.caption("Created %s \u00B7 used %d of %d \u00B7 expires %s" % (fmt_time(inv["created_at"]), inv["uses"], inv["max_uses"], fmt_time(inv["expires_at"])))
            if c2.button("Cancel link", key="inv_x_%d" % inv["invite_id"]):
                api("DELETE", "/invites/%d" % inv["invite_id"])
                S.pop("new_invite", None)
                st.rerun()
        # --- members
        st.markdown("**Members**")
        mem = api("GET", "/teams/%d/members" % tid)
        for m in (mem.json() if mem.ok else []):
            c1, c2, c3 = st.columns([4, 1.5, 1.5], vertical_alignment="center")
            c1.markdown("%s <span class='dv-badge'>%s</span>" % (escape(m["display_name"]), m["role"]), unsafe_allow_html=True)
            if m["user_id"] != S["profile"]["user_id"]:
                if m["role"] == "member" and c2.button("Make owner", key="mo_%d_%d" % (tid, m["user_id"]), use_container_width=True):
                    api("POST", "/teams/%d/members/%d/role" % (tid, m["user_id"]), json={"role": "owner"})
                    st.rerun()
                if c3.button("Remove", key="rm_%d_%d" % (tid, m["user_id"]), use_container_width=True):
                    r = api("DELETE", "/teams/%d/members/%d" % (tid, m["user_id"]))
                    if r.ok:
                        refresh_teams()
                        st.rerun()
                    else:
                        st.error(problem(r))
        # --- settings and maintenance
        with st.expander("Team settings and maintenance"):
            name = st.text_input("Team name", value=t["name"], key="tn_%d" % tid)
            desc = st.text_area("Description", value=t["description"], key="td_%d" % tid, max_chars=300)
            disc = st.checkbox("Others can find this team by searching its name", value=t["is_discoverable"], key="tdisc_%d" % tid)
            if st.button("Save settings", key="ts_%d" % tid):
                r = api("PATCH", "/teams/%d" % tid, json={"name": name, "description": desc, "is_discoverable": disc})
                if r.ok:
                    refresh_teams()
                    S["flash"] = "Team settings saved."
                    st.rerun()
                else:
                    st.error(problem(r))
            st.caption("Re-sync rebuilds missing version records from the files held in storage. It never changes or deletes anything.")
            if st.button("Run re-sync for this team", key="rs_%d" % tid):
                r = api("POST", "/resync", params={"team_id": tid})
                if r.ok:
                    d = r.json()
                    st.success("Checked %d stored versions, restored %d records." % (d["checked"], d["added"]))
                else:
                    st.error(problem(r))


def find_team_tab():
    q = st.text_input("Team name", placeholder="Search by team name", key="find_q")
    if st.button("Search", key="find_btn") or q:
        if len(q.strip()) < 2:
            st.caption("Type at least 2 letters.")
            return
        r = api("GET", "/teams/search", params={"q": q})
        if not r.ok:
            st.error(problem(r))
            return
        results = r.json()
        if not results:
            st.info("No team found with that name. Ask the team owner for an invite link instead.")
        for t in results:
            with st.container(key="card_find_%d" % t["team_id"]):
                c1, c2 = st.columns([5, 1.6], vertical_alignment="center")
                c1.markdown("<b>%s</b><div class='dv-muted'>%s \u00B7 %d member%s</div>" % (
                    escape(t["name"]), escape(t["description"] or "No description"), t["member_count"],
                    "" if t["member_count"] == 1 else "s"), unsafe_allow_html=True)
                if t["is_member"]:
                    c2.caption("You are a member")
                elif t["request_status"] == "pending":
                    c2.caption("Request sent")
                elif c2.button("Ask to join", key="join_%d" % t["team_id"], use_container_width=True):
                    rr = api("POST", "/teams/%d/join-requests" % t["team_id"])
                    if rr.ok:
                        S["flash"] = "Request sent. The team owner will review it."
                        st.rerun()
                    else:
                        st.error(problem(rr))


def create_team_tab():
    with st.form("new_team", clear_on_submit=True):
        name = st.text_input("Team name", placeholder="e.g. Musa & Co Chambers")
        desc = st.text_area("Description (optional)", max_chars=300)
        go = st.form_submit_button("Create team", type="primary")
    if go:
        r = api("POST", "/teams", json={"name": name, "description": desc})
        if r.ok:
            refresh_teams()
            S["flash"] = "Team created. You are the owner."
            switch_team = r.json()["team_id"]
            S["manage_team"] = switch_team
            st.rerun()
        else:
            st.error(problem(r))


# ----------------------------------------------------------------- profile and settings
def profile_page():
    prof = S["profile"]
    st.markdown("<div class='dv-h'>Your profile</div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 3], vertical_alignment="top")
    with c1:
        if S.get("avatar_raw"):
            with st.container(key="avatar_big"):
                st.image(S["avatar_raw"], width=130)
        else:
            st.markdown("<div class='dv-avatar-lg'>%s</div>" % initials(prof["display_name"]), unsafe_allow_html=True)
    with c2:
        with st.container(key="card_profile"):
            name = st.text_input("Full name", value=prof["display_name"], key="pf_name")
            st.text_input("Email", value=prof.get("email") or "-", disabled=True, key="pf_email")
            st.text_input("Username", value=prof["username"], disabled=True, key="pf_user")
            st.caption("Member since %s" % fmt_time(prof["created_at"]))
            if st.button("Save changes", type="primary", key="pf_save"):
                r = api("PATCH", "/me", json={"display_name": name})
                if r.ok:
                    S["profile"] = {**prof, **r.json()}
                    S["flash"] = "Profile saved."
                    st.rerun()
                else:
                    st.error(problem(r))
    st.markdown("#### Profile picture")
    pic = st.file_uploader("Choose a picture (PNG or JPG, up to 3 MB)", type=["png", "jpg", "jpeg"], key="pf_pic")
    cc1, cc2, _ = st.columns([1.2, 1.2, 3])
    if cc1.button("Use this picture", key="pf_pic_ok", disabled=pic is None):
        r = api("POST", "/me/avatar", files={"file": (pic.name, pic.getvalue())})
        if r.ok:
            load_session()
            S["flash"] = "Profile picture updated."
            st.rerun()
        else:
            st.error(problem(r))
    if prof["has_avatar"] and cc2.button("Remove picture", key="pf_pic_rm"):
        api("DELETE", "/me/avatar")
        load_session()
        st.rerun()
    st.markdown("#### Your teams")
    if not prof["teams"]:
        st.caption("You are not in any team yet.")
    for t in prof["teams"]:
        st.markdown("\u2022 **%s** <span class='dv-badge'>%s</span>" % (escape(t["name"]), t["role"]), unsafe_allow_html=True)


def choose_theme():
    S["theme"] = S["theme_select"]


def settings_page():
    st.markdown("<div class='dv-h'>Settings</div>", unsafe_allow_html=True)
    st.markdown("#### Theme")
    st.caption("Choose how DocVault looks, from clean black and white to colourful and dark themes. DocVault remembers your choice.")
    if S["theme"] not in THEMES:
        S["theme"] = DEFAULT_THEME
    st.selectbox("Theme", list(THEMES), index=list(THEMES).index(S["theme"]), key="theme_select",
                 format_func=lambda k: THEMES[k]["label"], on_change=choose_theme)
    if S["theme"] != S["profile"]["theme"]:
        r = api("PATCH", "/me", json={"theme": S["theme"]})
        if r.ok:
            S["profile"]["theme"] = S["theme"]
    st.markdown("#### Password")
    change_password_form()
    st.markdown("#### Maintenance")
    st.caption("Re-sync rebuilds missing version records of your private files from the files held in storage. "
               "It never changes or deletes anything. (Team owners re-sync a team from Teams, Manage.)")
    if st.button("Run re-sync for my private files", key="rs_mine"):
        r = api("POST", "/resync")
        if r.ok:
            d = r.json()
            st.success("Checked %d stored versions, restored %d records." % (d["checked"], d["added"]))
        else:
            st.error(problem(r))


def change_password_form(forced: bool = False):
    with st.form("chpw", clear_on_submit=True):
        cur = st.text_input("Temporary password" if forced else "Current password", type="password")
        new1 = st.text_input("New password (8+ characters)", type="password")
        new2 = st.text_input("Repeat the new password", type="password")
        go = st.form_submit_button("Change password", type="primary")
    if go:
        if new1 != new2:
            st.error("The two new passwords do not match.")
            return
        r = api("POST", "/change-password", json={"current_password": cur, "new_password": new1})
        if r.ok:
            if forced:
                S["user"]["must_change_password"] = False
                load_session()
                st.rerun()
            st.success("Your password was changed.")
        else:
            st.error(problem(r))


PAGES = {"files": files_page, "upload": upload_page, "teams": teams_page, "profile": profile_page, "settings": settings_page}


def app_screen():
    if S["user"].get("must_change_password"):
        inject_theme()
        _, mid, _ = st.columns([1, 1.25, 1])
        with mid:
            st.markdown(brand_html(), unsafe_allow_html=True)
            with st.container(key="card_auth"):
                st.subheader("Choose your own password")
                st.write("You are using a temporary password. Choose a new one to continue.")
                change_password_form(forced=True)
        return
    inject_theme()
    flash()
    topbar()
    with st.container(key="page_" + S["page"]):
        PAGES[S["page"]]()


# ----------------------------------------------------------------- main
if "token" not in S:
    auth_screen()
else:
    app_screen()
