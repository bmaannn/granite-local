"""
main.py — Wispr Local: hold-to-talk AI dictation pipeline.

Responsibility: Global hotkey listener that orchestrates the full pipeline:
  Audio Capture → Speech-to-Text → AI Polish → Text Injection

Usage:
  python main.py

Hold Right-Cmd (⌘) to record. Release to transcribe, polish, and paste.
Press Ctrl+C to quit.

Measured felt latency on M1 16GB (key release → text pasted, models warm):
  short dictation (~2s)  : ~1.9s
  long dictation (~14s)  : ~3.1s  (phrases transcribe while you speak)

macOS permissions required before running:
  1. Microphone        — System Settings → Privacy → Microphone
  2. Accessibility     — System Settings → Privacy → Accessibility
  3. Input Monitoring  — System Settings → Privacy → Input Monitoring
  (Grant all three to Terminal.app or your Python launcher)
"""

import sys
import time
import threading
from pynput import keyboard

import audio
import stream
import transcribe
import polish
import inject
import overlay
import history
import history_ui
import learn

# ── Configuration ─────────────────────────────────────────────────────────────

# The key that triggers record-on-hold / stop-on-release.
# Blueprint spec: Right-Cmd. Change to e.g. keyboard.Key.alt_r for Right-Alt.
HOTKEY = keyboard.Key.cmd_r

# Tap this key to toggle the dictation-history panel (click an entry to paste).
HISTORY_HOTKEY = keyboard.Key.alt_r

# If True, show a visual indicator in the terminal while recording.
VERBOSE_STATUS = True

# ── State ─────────────────────────────────────────────────────────────────────

# _recording_flag: set while the key is held, cleared atomically on first
# release event. Using an Event instead of a bare bool so the clear+check
# is atomic — prevents a second release event from spawning a second pipeline.
_recording_flag = threading.Event()
_pipeline_lock  = threading.Lock()

# ── Pipeline ──────────────────────────────────────────────────────────────────

def _run_pipeline():
    """
    Run the full STT → Polish → Inject pipeline in a background thread.

    We run this off the hotkey listener thread so the listener remains
    responsive (e.g. to a new hotkey press) while the pipeline runs.
    Pynput callbacks must return quickly; blocking them causes missed events.
    """
    with _pipeline_lock:
        # ── Stage 1+2: Stop recording, drain streaming transcription ───────
        # Phrases spoken earlier were already transcribed in the background
        # while the key was held — stop() only transcribes the final phrase.
        t0 = time.perf_counter()
        _status("Transcribing…")
        overlay.transcribing()
        raw_text = stream.stop()
        t2 = time.perf_counter()

        if not raw_text.strip():
            _status("No speech detected.")
            overlay.hide()
            return

        # ── Stage 3: Polish (Ollama) ────────────────────────────────────────
        _status("Polishing…")
        overlay.polishing()
        polished_text = polish.run(raw_text)
        t3 = time.perf_counter()

        if not polished_text.strip():
            _status("Polish returned empty output.")
            overlay.hide()
            return

        # ── Stage 4: Inject into focused app ───────────────────────────────
        inject.paste(polished_text)
        t4 = time.perf_counter()

        overlay.done()

        # ── Save to history + learn new vocabulary (both best-effort) ──────
        try:
            history.add(raw_text, polished_text)
        except Exception as exc:
            _status(f"history save failed: {exc}")
        try:
            learn.observe(polished_text)
        except Exception as exc:
            _status(f"vocab learning failed: {exc}")

        # ── Timing report ──────────────────────────────────────────────────
        _status(
            f"Done in {t4-t0:.2f}s  "
            f"[STT drain: {t2-t0:.2f}s | "
            f"LLM: {t3-t2:.2f}s | Inject: {t4-t3:.2f}s]"
        )


# ── Hotkey callbacks ──────────────────────────────────────────────────────────

def on_press(key):
    if key == HISTORY_HOTKEY:
        history_ui.toggle()
        return

    # Ignore anything that isn't exactly Right-Cmd.
    if key != HOTKEY:
        return

    # Already recording — key is being held down (repeat events). Ignore.
    if _recording_flag.is_set():
        return

    if _pipeline_lock.locked():
        _status("⚠ Still processing — wait before recording again.")
        return

    _recording_flag.set()

    # Hook audio level into overlay so orb pulses with voice.
    audio.on_level = overlay.level

    audio.start_recording()
    stream.start()
    overlay.recording()
    _status("● Recording…  (release ⌘ to stop)")


def on_release(key):
    # Ignore anything that isn't exactly Right-Cmd.
    if key != HOTKEY:
        return

    if not _recording_flag.is_set():
        return

    # Clear atomically BEFORE spawning the thread — duplicate release events
    # arriving while the pipeline runs will see is_set()==False and bail.
    _recording_flag.clear()

    # Stop level updates — we're no longer recording.
    audio.on_level = None

    thread = threading.Thread(target=_run_pipeline, daemon=True)
    thread.start()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status(msg: str):
    if VERBOSE_STATUS:
        print(f"[wispr] {msg}")


def _warm_up():
    """
    Pre-load the Whisper model and prime the Ollama client at startup so
    the first dictation doesn't pay the cold-start penalty.

    Blueprint is silent on warm-up; added as a UX best practice.
    """
    # Fail loudly if we can't post keystrokes — otherwise every dictation
    # would silently vanish (CGEventPost drops events without Accessibility).
    if not inject.check_post_event_access():
        print(
            "\n[wispr] ⚠️  PASTE WILL NOT WORK — Accessibility permission missing.\n"
            "        Grant it to your terminal app in:\n"
            "        System Settings → Privacy & Security → Accessibility\n"
            "        (macOS should have just shown a prompt. After granting,\n"
            "        QUIT and RESTART this app — macOS applies it on launch.)\n"
        )

    print("[wispr] Warming up models (first run may take 30–60s) …")
    import numpy as np

    # Tiny silent audio to force Whisper model download + load.
    dummy = np.zeros(SAMPLE_RATE * 1, dtype=np.float32)  # 1s silence
    try:
        transcribe.run(dummy)
    except Exception as exc:
        print(f"[wispr] Whisper warm-up warning: {exc}")

    # Tiny Ollama call to verify connectivity and load model into VRAM.
    try:
        polish.run("Hello.")
    except Exception as exc:
        print(f"[wispr] Ollama warm-up warning: {exc}")

    print("[wispr] Ready. Hold Right-⌘ to dictate. Tap Right-⌥ for history. "
          "Ctrl+C to quit.\n")


# Expose SAMPLE_RATE for warm-up dummy audio generation.
SAMPLE_RATE = audio.SAMPLE_RATE


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    _warm_up()

    listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
        # suppress=False → do NOT suppress the hotkey from reaching other apps.
        # Blueprint is silent; suppressing Right-Cmd would break normal usage.
        suppress=False,
    )
    listener.start()

    try:
        # Keep the main thread alive. listener runs in its own thread.
        while listener.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[wispr] Exiting.")
    finally:
        listener.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
