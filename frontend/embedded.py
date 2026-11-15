"""Runs the DocVault API inside the Streamlit process, for hosts that run only one program.

Streamlit Community Cloud runs a single Streamlit app, so the API cannot be a separate service there.
Set DOCVAULT_EMBED=1 and the API starts in a background thread on 127.0.0.1 the first time the app loads.
Everything else (settings, secrets, the S3 bucket) is read from the environment exactly as before.
"""
import os
import sys
import threading
import time
import urllib.request

_lock = threading.Lock()
_started = False


def _port() -> int:
    return int(os.environ.get("DOCVAULT_EMBED_PORT", "8765"))


def _healthy() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/health" % _port(), timeout=1)
        return True
    except Exception:
        return False


def start_if_enabled() -> None:
    global _started
    if os.environ.get("DOCVAULT_EMBED") != "1":
        return
    PORT = _port()
    os.environ["DOCVAULT_API"] = "http://127.0.0.1:%d" % PORT
    with _lock:
        if _started and _healthy():
            return
        if _healthy():
            _started = True
            return
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        import uvicorn
        from backend.main import create_app
        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=PORT, log_level="info"))
        threading.Thread(target=server.run, name="docvault-api", daemon=True).start()
        for _ in range(60):                                  # wait up to 30 seconds for the API to answer
            if _healthy():
                break
            time.sleep(0.5)
        _started = True
