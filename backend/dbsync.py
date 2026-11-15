"""Keeps the SQLite database safe on free hosts whose disk is wiped on every restart.

When STORAGE_BACKEND=s3 and DB_BACKUP_SECONDS is above 0:
  * at start-up, if there is no local database, the newest backup is downloaded from the bucket;
  * every DB_BACKUP_SECONDS (and once more when the server stops) a consistent snapshot is uploaded
    if the database changed.
The snapshot is stored under _system/ in the same bucket. It is ignored by re-sync, because it is not a user file.
Every upload is a new bucket version, so add a lifecycle rule that keeps only the latest version of _system/.
"""
import logging
import os
import sqlite3
import tempfile
import threading

log = logging.getLogger("docvault")
KEY = "_system/docvault.db"


def enabled(settings, storage) -> bool:
    return settings.db_backup_seconds > 0 and getattr(storage, "name", "") == "s3" and hasattr(storage, "read_latest")


def restore_if_missing(settings, storage) -> bool:
    """Download the newest backup when this host has no database yet. Returns True if one was restored."""
    if not enabled(settings, storage):
        return False
    if os.path.exists(settings.db_path) and os.path.getsize(settings.db_path) > 0:
        return False
    data = storage.read_latest(KEY)
    if not data:
        log.info("No database backup found in the bucket; starting with an empty database.")
        return False
    folder = os.path.dirname(os.path.abspath(settings.db_path))
    os.makedirs(folder, exist_ok=True)
    with open(settings.db_path, "wb") as fh:
        fh.write(data)
    log.warning("Restored the database from the bucket backup (%d bytes).", len(data))
    return True


def snapshot(db_path: str) -> bytes:
    """A consistent copy of the database, made with SQLite's own backup call."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src, dst = sqlite3.connect(db_path), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        os.remove(tmp)


class Backup:
    def __init__(self, settings, storage):
        self.settings, self.storage = settings, storage
        self._last = None
        self._stop = threading.Event()
        self._thread = None

    def _fingerprint(self):
        try:
            st = os.stat(self.settings.db_path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def run_once(self) -> bool:
        fp = self._fingerprint()
        if fp is None or fp == self._last:
            return False
        try:
            self.storage.put_object(KEY, snapshot(self.settings.db_path), {"kind": "db-backup"})
        except Exception:                                   # never let a backup problem stop the app
            log.exception("Database backup to the bucket failed; will try again.")
            return False
        self._last = fp
        return True

    def _loop(self):
        while not self._stop.wait(self.settings.db_backup_seconds):
            self.run_once()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="docvault-db-backup", daemon=True)
            self._thread.start()
            log.info("Database backup to the bucket every %d seconds.", self.settings.db_backup_seconds)

    def stop(self):
        self._stop.set()
        self.run_once()
