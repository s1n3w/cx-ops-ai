"""Desktop app: Ollama + the local UI server + a Brave app-mode window. Closing the window quits.

Run:  pythonw -m cxops.gui      ("CX Ops AI.exe" does this; no console window)

Brave gets its own small profile, so the window is a separate browser process this launcher can
wait on, and it never touches the user's normal Brave profile. Ollama and the window are both in
kill-on-close job objects, so they stop even if this process dies. (Pattern from Ask Data.)
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from . import data, llm
from .ollama import _kill_on_close_job, ensure_running
from .web.server import AppState, start_server

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "cx-ops-ai"
BRAVE_CANDIDATES = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
    Path(os.environ["LOCALAPPDATA"]) / "BraveSoftware/Brave-Browser/Application/brave.exe",
]


def message_box(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "CX Ops AI", 0x10)


def warm_up_model() -> None:
    try:
        llm.chat([{"role": "user", "content": "Reply OK."}])
        AppState.model_ready = True
    except Exception as e:
        AppState.model_error = f"{type(e).__name__}: {e}"


def prepare_window_profile(profile: Path) -> None:
    """Turn off Brave's P3A analytics notice and usage ping in the window's own profile."""
    profile.mkdir(parents=True, exist_ok=True)
    local_state = profile / "Local State"
    try:
        state = json.loads(local_state.read_text(encoding="utf-8")) if local_state.exists() else {}
    except (OSError, ValueError):
        state = {}
    brave = state.setdefault("brave", {})
    brave.setdefault("p3a", {}).update({"enabled": False, "notice_acknowledged": True})
    brave.setdefault("stats", {})["reporting_enabled"] = False
    local_state.write_text(json.dumps(state), encoding="utf-8")


def open_window(url: str) -> subprocess.Popen:
    brave = next((p for p in BRAVE_CANDIDATES if p.exists()), None)
    if not brave:
        raise SystemExit("Brave isn't installed, and the app window needs it.")
    profile = APP_DIR / "window-profile"
    prepare_window_profile(profile)
    return subprocess.Popen([str(brave), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-extensions", "--window-size=1320,940"])


def main() -> None:
    APP_DIR.mkdir(exist_ok=True)
    data.use_custom = True  # the app answers from your own articles too; the scored tests never do
    log = open(APP_DIR / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log  # pythonw has no console
    try:
        with ensure_running():
            threading.Thread(target=warm_up_model, daemon=True).start()
            server = start_server()
            window = open_window(f"http://127.0.0.1:{server.server_address[1]}/")
            job = _kill_on_close_job(window)  # noqa: F841 - closes the window if we die
            window.wait()
            server.shutdown()
    except SystemExit as e:
        message_box(str(e))
    except Exception:
        traceback.print_exc()
        message_box("CX Ops AI hit an unexpected error. Details are in\n" + str(APP_DIR / "app.log"))


if __name__ == "__main__":
    main()
