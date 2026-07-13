"""
inject.py — Paste polished text into the currently focused application.

Uses macOS CGEvent (via pyobjc) to post a synthetic Cmd+V directly into
the event stream — faster and more reliable than pyautogui, and crucially
does NOT generate pynput-visible keystrokes that could cause a double-paste.
Falls back to pbpaste/osascript if pyobjc is unavailable.
"""

import time
import subprocess
import pyperclip

# Settle time after writing to clipboard before posting the paste event.
CLIPBOARD_SETTLE_S = 0.08

# How long after pasting before restoring original clipboard.
RESTORE_DELAY_S = 0.20

# ── Permission check ──────────────────────────────────────────────────────────

def check_post_event_access() -> bool:
    """
    Return True if this process may post synthetic keystrokes (Cmd+V).

    Without Accessibility permission, CGEventPost fails SILENTLY — the paste
    just never happens. Call this at startup so the user finds out immediately.
    Calling CGRequestPostEventAccess registers the app in System Settings →
    Privacy & Security → Accessibility and shows the system prompt.
    """
    try:
        from Quartz import CGPreflightPostEventAccess, CGRequestPostEventAccess
    except ImportError:
        return True  # can't check — assume OK, osascript fallback may still work

    if CGPreflightPostEventAccess():
        return True

    CGRequestPostEventAccess()  # triggers the macOS permission prompt
    return False


# ── Try pyobjc CGEvent path ───────────────────────────────────────────────────

def _paste_cgevent(text: str) -> bool:
    """
    Post a Cmd+V keystroke using CoreGraphics CGEvent.
    This bypasses pynput's listener entirely — CGEvent goes straight to the
    window server, so pynput never sees the synthetic keypress.
    Returns True on success, False if pyobjc unavailable.
    """
    try:
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventPost,
            CGEventSetFlags,
            kCGEventFlagMaskCommand,
            kCGHIDEventTap,
            kCGSessionEventTap,
        )
    except ImportError:
        return False

    # Key code 9 = 'v' on US keyboard layout
    V_KEY = 9

    # Key down with Cmd flag
    ev_down = CGEventCreateKeyboardEvent(None, V_KEY, True)
    CGEventSetFlags(ev_down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, ev_down)

    time.sleep(0.05)

    # Key up with Cmd flag
    ev_up = CGEventCreateKeyboardEvent(None, V_KEY, False)
    CGEventSetFlags(ev_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, ev_up)

    return True


# ── Public API ────────────────────────────────────────────────────────────────

def paste(text: str) -> None:
    """
    Inject `text` at the current cursor position in whatever app has focus.
    Preserves the user's original clipboard contents.
    """
    if not text:
        return

    # Save original clipboard
    try:
        original = pyperclip.paste()
    except Exception:
        original = ""

    try:
        # Write text to clipboard
        pyperclip.copy(text)
        time.sleep(CLIPBOARD_SETTLE_S)

        # Post Cmd+V via CGEvent (invisible to pynput)
        if not _paste_cgevent(text):
            # Fallback: osascript keystroke — also invisible to pynput
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
                check=False
            )

        time.sleep(RESTORE_DELAY_S)
        print(f"[inject] Pasted {len(text)} chars.")

    except Exception as exc:
        print(f"[inject] ERROR: {exc}")

    finally:
        # Restore original clipboard
        try:
            pyperclip.copy(original)
        except Exception:
            pass
