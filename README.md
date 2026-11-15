# DocVault: Cloud-Native Document Versioning System

"Git for files" for non-technical people and teams. Every upload needs a **commit message**, every version is kept
in an **Amazon S3 bucket** (Versioning + Object Lock), the history is a **Time Machine timeline**, and any version
can be restored with **one click** (a rollback adds a new version; nothing is deleted).

People **sign up with their email**, keep **private files**, and can **create or join teams** (by invite link, or
by searching a team and asking to join) to share files and history.

```
backend/    FastAPI backend: config, db (SQLite), security, storage (S3 + local), services, teams, mailer, main (API)
frontend/   Streamlit interface (app.py) and its themes, logo and styling (theme.py)
scripts/    setup_s3.py (create the bucket), create_admin.py (create an account), reset_user.py (unlock an account)
tests/      test_core.py, test_teams.py, test_s3_logic.py (no installs needed), test_api.py (needs requirements)
```

## 1. Quick start (no AWS needed: "local" mode)

Requires Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate               # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env               # Mac/Linux: cp .env.example .env
# edit .env: set SECRET_KEY (leave STORAGE_BACKEND=local)

python -m uvicorn backend.main:create_app --factory --reload      # window 1: the backend
python -m streamlit run frontend/app.py                           # window 2: the interface (http://localhost:8501)
```

**First use**
1. Open the interface and choose **Create an account** (name, email, password).
2. A 6-digit code is sent to your email. In demo mode (`SMTP_HOST` empty) the code is **printed in the backend
   window**. Type it in to verify and you are logged in.
3. **Files / Upload** work in your private space ("My files"). Use the workspace selector in the top bar to switch
   to a team's files.
4. Open **Teams** to create a team, search for one and ask to join, or paste nothing at all: if someone sends you an
   invite link, just open it, log in or sign up, and you are added.
5. Click your picture (top right) for **Profile**, **Settings** (themes, password), and **Log out**.

You can still log in with a username (the first account made by `ADMIN_PASSWORD` in `.env` is called `admin`).

### Editing in the browser
Open a file and press **Edit in browser**; write a commit message and **Save as new version**. No download or
re-upload. **Upload > Create a new blank document** makes a new Word, Excel, PowerPoint, text, Markdown or CSV file.
- **Text and code** (txt, md, json, html, py, js, and more): a text editor, with a preview for Markdown, HTML and SVG.
- **Word (.docx)**: edit the text; the formatting of untouched paragraphs is kept. Tables are edited as grids.
- **Excel (.xlsx) and CSV**: a spreadsheet grid, one tab per sheet. Charts and pictures inside a spreadsheet are lost on save.
- **PowerPoint (.pptx)**: click the text on a slide and type. Toolbar: bold, italic, underline, size, colour, alignment; add, copy, reorder and delete slides; add and delete text boxes; drag to move and resize boxes. Design and pictures are kept.
- **Pictures**: rotate, flip, black and white, resize.
- **PDF, video, audio**: view only. If someone saves a newer version while you edit, you are warned before you overwrite it.
- Not supported: live co-editing, and bold/italic toolbars (these need an office server such as ONLYOFFICE).

### Folders
On **Files**, open **New folder** to make a folder (inside the folder you are in). Click a folder to open it; the buttons above the
list take you back up. **Upload** has a **Folder** box that starts in the folder you were looking at. A folder is part of the
storage key (`u3/Design/Logo.png`), so a file stays where it was uploaded; re-sync restores the folder from the key. Only an
empty folder can be deleted. Files and folders cannot be moved or renamed.

### Comparing two versions
Open a file with two or more versions and press **Compare versions**. Text, code, Word, PowerPoint and PDF files are compared
line by line (changed words are marked), Excel files cell by cell, pictures pixel by pixel (changes shown in red); other files by
size and checksum. Nothing is changed by comparing.

### Staying logged in
The login token is also kept in a browser cookie (`dv_token`), so refreshing the page does not log you out. It ends when the
token expires (`TOKEN_HOURS`, default 8) or when you press **Log out**.

### Teams, in short
- **Owner** (whoever creates the team): creates **invite links** (shown once, valid 7 days, can be cancelled), approves
  or declines **join requests**, makes other owners, removes members, edits the team, and runs **re-sync**.
- **Member**: sees and uses the team's files, can roll back, and can leave the team.
- **Find a team** searches by name. Joining by search needs an owner's approval. Owners can hide a team from search.
- Files in a team are visible only to its members. Files in "My files" are visible only to you.

### Passwords and email
- Login problems are written in the backend window (for example *wrong password for 'amina' (1 tries left)*), so you can see why a login was refused. An empty field is never counted as a wrong password.
- **Forgot password** (login screen): enter your email or username, receive a 6-digit code (15 minutes, 5 wrong
  tries, one request per minute), choose a new password. It also unlocks an account locked by wrong passwords. A locked account also opens again by itself after `LOCK_MINUTES` (default 15).
- For real email, fill in the `SMTP_*` lines in `.env` (the file explains how to use Gmail with an app password).
- An account without an email (for example one made by the first version) can be unlocked with
  `python scripts/reset_user.py`.
- Your **existing database upgrades automatically** the next time the backend starts. Files from the first version
  move into a team called **Default team** that contains all existing users.

## 2. Use your real S3 bucket

1. In the AWS console create an IAM user that can create buckets and run `aws configure` with its keys (use it only
   for step 2).
2. Create the bucket (Object Lock can only be enabled when a bucket is created):
   ```bash
   python scripts/setup_s3.py --bucket your-unique-bucket-name --region eu-west-1 --retention-days 1
   ```
   While developing keep `--retention-days 1`: during the retention period stored versions cannot be deleted.
3. Create a limited application user with only this policy (replace `BUCKET`). It has **no delete permissions**,
   which is what makes the history immutable for the application:
   ```json
   {"Version": "2012-10-17", "Statement": [
     {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::BUCKET/*"},
     {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:ListBucketVersions"],
      "Resource": "arn:aws:s3:::BUCKET"}
   ]}
   ```
   Run `aws configure` again with this user's access key.
4. In `.env` set `STORAGE_BACKEND=s3`, `S3_BUCKET=...`, `AWS_REGION=...` and restart the backend.

Files are stored under `t<team id>/<file name>` (team files) or `u<user id>/<file name>` (private files).

### Test against real S3 (once, and keep screenshots for Chapter Four)
- Upload a file twice; in the S3 console turn on **Show versions** and confirm two versions.
- Roll back to version 1; confirm a third version appears and the first two are unchanged.
- Delete `data/docvault.db`, restart, sign up again as the same first person and re-create your team (private files
  and team files are found by the account number and team number in their storage path, so create them in the
  same order), then press **Run re-sync** (Teams, Manage for team files; Settings for your private files): the
  history comes back with commit messages and authors.
- With the application user's keys run `aws s3api delete-object --bucket BUCKET --key t1/report.docx --version-id VERSION_ID`:
  it must fail with *Access Denied*.

## Hosting for free (Streamlit Community Cloud + your S3 bucket)

The whole app runs as one free Streamlit app. The API starts inside it (`frontend/embedded.py`, switched on with
`DOCVAULT_EMBED=1`), and every file version stays in your Amazon S3 bucket, so Versioning and Object Lock are unchanged.
- **Streamlit Community Cloud**: free, no card, deploys from GitHub. An app with no visitors for about 12 hours goes to
  sleep; opening its address wakes it up in under a minute.
- **The database** (accounts and teams) is backed up to the bucket every few minutes and restored automatically after a
  restart (`DB_BACKUP_SECONDS`, see `backend/dbsync.py`). Profile pictures are not backed up and come back empty.

Steps:
1. **Build the upload folder**: `python scripts/make_repo.py` makes `github_build/` (code only: no `.env`, database or files).
2. **GitHub**: create a free account, then *New repository* (for example `docvault`, empty, no README). In `github_build/` run:
   ```bash
   git init
   git add .
   git commit -m "DocVault"
   git branch -M main
   git remote add origin https://github.com/YOUR_NAME/docvault.git
   git push -u origin main
   ```
   When git asks you to sign in, use the browser window it opens (or a personal access token as the password).
3. **S3 keys for the app**: it cannot use `aws configure`, so give it the access key of your limited application user
   (the policy in section 2, without delete permissions), never your administrator keys. To keep the accounts you made on
   your computer, upload your local database once before the first start:
   `aws s3api put-object --bucket YOUR_BUCKET --key _system/docvault.db --body data/docvault.db`
   Add a lifecycle rule on the bucket for the prefix `_system/` that expires old (noncurrent) versions.
4. **Streamlit Community Cloud**: go to share.streamlit.io, sign in with GitHub, click *Create app*, choose your repository,
   branch `main`, and main file path **`frontend/app.py`**. Open *Advanced settings*, pick Python 3.12, and paste this into
   *Secrets* (fill in your own values):
   ```toml
   DOCVAULT_EMBED = "1"
   SECRET_KEY = "a long random text"
   ADMIN_PASSWORD = "password for the first account, called admin"
   STORAGE_BACKEND = "s3"
   S3_BUCKET = "your-bucket-name"
   AWS_REGION = "your-bucket-region"
   AWS_ACCESS_KEY_ID = "limited user's access key id"
   AWS_SECRET_ACCESS_KEY = "limited user's secret key"
   DB_BACKUP_SECONDS = "120"
   DOCVAULT_APP_URL = "https://YOUR-APP-NAME.streamlit.app"
   SMTP_HOST = "smtp.gmail.com"
   SMTP_PORT = "587"
   SMTP_USER = "you@gmail.com"
   SMTP_PASSWORD = "gmail app password"
   SMTP_FROM = "you@gmail.com"
   ```
   Click *Deploy*. Make `SECRET_KEY` with `python -c "import secrets; print(secrets.token_hex(32))"`.
   The first build takes a few minutes. After it is running, set `DOCVAULT_APP_URL` to the real address if it differs.

**Email is required for sign-up.** Without `SMTP_*` the 6-digit code is only printed in the app log, so other people
cannot verify their address. The free option is a Gmail account with 2-step verification and an *App password*.

Check it once: upload a file twice and confirm two versions in the S3 console (*Show versions*), then use the app's
*Reboot* option and confirm you can still log in. Free tiers can change; for a long-lived service use a paid plan or
your own server. The app has about 1 GB of memory, so keep very large uploads in mind (files are read into memory).

## 3. Tests

```bash
python -m unittest discover -s tests -v     # runs without installs (the API test file is skipped)
python -m pytest tests/test_api.py -v       # end-to-end API tests (needs: pip install -r requirements.txt)
```

## 4. How it maps to the report

| Report | Where |
|---|---|
| Upload with mandatory commit message | `VersionService.upload`, `POST /upload` |
| File list, timeline, download, rollback | `list_files`, `list_versions`, `download_link`, `rollback` |
| Sign-up, email check, login by email or username | `services.signup`, `verify_email`, `authenticate` |
| Change and forgotten password | `services.change_password`, `request_reset`, `reset_password` |
| Teams, invite links, join requests | `backend/teams.py` |
| Private and team files | `file_access`, key prefixes `u<id>/` and `t<id>/` |
| Profile, picture, black-and-white themes (Google Sans font) | `services.get_profile`, `update_profile`, `save_avatar`, `frontend/theme.py` |
| Re-sync | `VersionService.resync`, `POST /resync` |
| Immutability | S3 Versioning + Object Lock; no delete method in `storage.py`; no delete IAM permission |

Storage is written first and the database record second, so the database never describes a version that does not
exist. If the record fails after the upload, run a re-sync.

## 5. Known limits

- Platform-wide administration was removed: each team is managed by its owners.
- No mobile app. Files and folders cannot be moved or renamed. Comparison shows text, cells and pixels, not formatting.
- Every version is stored in full, so storage grows with each version.
- Governance-mode Object Lock can be bypassed by an AWS user who has the special permission.
- Files are read into memory on upload (limit `MAX_UPLOAD_MB`, default 200 MB).
- The login cookie can be read by scripts of the page; use HTTPS (the cookie is then marked Secure).
- Sessions already open stay valid after a password change until they expire (`TOKEN_HOURS`).
- Run behind HTTPS before using it outside a network you trust.
