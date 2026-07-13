"""
overlay.py — Floating status pill controller.

Launches overlay_process.py as a subprocess that owns the Cocoa NSPanel.
Communicates via stdin — sends single-line state strings.
This sidesteps the "NSWindow must be on main thread" restriction entirely.
"""

import subprocess
import sys
import os
import threading
import time

# Path to the companion process script.
_SCRIPT = os.path.join(os.path.dirname(__file__), "overlay_process.py")

# Python executable inside our venv.
_PYTHON = sys.executable

_proc: subprocess.Popen | None = None
_lock  = threading.Lock()


def _get_proc() -> subprocess.Popen | None:
    global _proc
    with _lock:
        # Start or restart the subprocess if it's gone.
        if _proc is None or _proc.poll() is not None:
            try:
                _proc = subprocess.Popen(
                    [_PYTHON, _SCRIPT],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # Brief pause so NSApplication can initialise before first message.
                time.sleep(0.4)
            except Exception as e:
                print(f"[overlay] Failed to start overlay process: {e}")
                _proc = None
    return _proc


def _send(state: str):
    proc = _get_proc()
    if proc is None:
        return
    try:
        proc.stdin.write((state + "\n").encode())
        proc.stdin.flush()
    except Exception:
        # Process died — will be restarted on next call.
        global _proc
        with _lock:
            _proc = None


# Eagerly start the subprocess on import so it's ready when first needed.
threading.Thread(target=_get_proc, daemon=True).start()


# ── Public API ────────────────────────────────────────────────────────────────

def recording():          _send("recording")
def transcribing():       _send("transcribing")
def polishing():          _send("polishing")
def done():               _send("done")
def hide():               _send("hidden")
def level(val: float):    _send(f"level:{val:.3f}")
