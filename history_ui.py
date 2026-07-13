"""
history_ui.py — Controller for the history panel subprocess.

Same pattern as overlay.py: launches history_panel.py as a subprocess that
owns the Cocoa panel, and talks to it over stdin.
"""

import os
import subprocess
import sys
import threading
import time

_SCRIPT = os.path.join(os.path.dirname(__file__), "history_panel.py")
_PYTHON = sys.executable

_proc: subprocess.Popen | None = None
_lock = threading.Lock()


def _get_proc() -> subprocess.Popen | None:
    global _proc
    with _lock:
        if _proc is None or _proc.poll() is not None:
            try:
                _proc = subprocess.Popen(
                    [_PYTHON, _SCRIPT],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.4)   # let NSApplication initialise
            except Exception as e:
                print(f"[history] Failed to start history panel: {e}")
                _proc = None
    return _proc


def _send(cmd: str):
    proc = _get_proc()
    if proc is None:
        return
    try:
        proc.stdin.write((cmd + "\n").encode())
        proc.stdin.flush()
    except Exception:
        global _proc
        with _lock:
            _proc = None


# Eagerly start the subprocess so the first ⌥ tap opens instantly.
threading.Thread(target=_get_proc, daemon=True).start()


# ── Public API ────────────────────────────────────────────────────────────────

def toggle():   _send("toggle")
def hide():     _send("hide")
