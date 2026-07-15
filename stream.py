"""
stream.py — Incremental transcription while the user is still speaking.

The Wispr Flow trick: don't wait for key-release to start transcribing.
While recording, a worker thread watches the audio buffer. Whenever VAD
sees a finished phrase (speech followed by ≥ SILENCE_CLOSE_S of silence),
that phrase is transcribed immediately in the background. On key-release
only the final, still-open phrase remains — so perceived latency is the
cost of transcribing one short phrase instead of the whole dictation.

Usage (from main.py):
    stream.start()                  # after audio.start_recording()
    ...user speaks...
    raw_text = stream.stop()        # stops audio, drains queue, joins text
"""

import threading
import time

import numpy as np

import audio
import transcribe
import vocab

# ── Tuning ────────────────────────────────────────────────────────────────────

# A phrase is "closed" (safe to transcribe) once this much silence follows it.
# Lower → phrases dispatch sooner but risk splitting mid-sentence pauses.
SILENCE_CLOSE_S = 0.6

# Don't bother running VAD until at least this much new audio has accumulated.
MIN_TAIL_S = 1.2

# How often the worker polls for new closed phrases (when idle).
POLL_INTERVAL_S = 0.25

# ── State ─────────────────────────────────────────────────────────────────────

_worker: threading.Thread | None = None
_stop_event = threading.Event()
_wake = threading.Event()   # set on stop() to cut the worker's poll sleep short

# Samples already dispatched to transcription (offset into the full buffer).
_committed = 0

# Transcribed phrase texts, in spoken order (worker is single-threaded, so
# append order == spoken order — no reordering needed).
_texts: list[str] = []


# ── Worker ────────────────────────────────────────────────────────────────────

def _closed_segments(tail: np.ndarray, is_final: bool) -> tuple[list, int]:
    """
    Find phrases in `tail` that are safe to transcribe now.

    Returns (segments, consumed) where segments is a list of (start, end)
    sample ranges and consumed is how many samples of `tail` are settled.
    While recording, a phrase is closed only if ≥ SILENCE_CLOSE_S of silence
    follows it (otherwise the user may still be mid-word). On the final pass
    every detected phrase is closed by definition.
    """
    stamps = audio.vad_segments(tail)
    if not stamps:
        # No speech at all — everything so far is silence; consume it except
        # a safety margin (VAD padding could extend a phrase slightly back).
        margin = int(SILENCE_CLOSE_S * audio.SAMPLE_RATE)
        return [], max(0, len(tail) - margin) if not is_final else len(tail)

    silence_gap = int(SILENCE_CLOSE_S * audio.SAMPLE_RATE)
    segments = []
    consumed = 0
    for st in stamps:
        closed = is_final or (len(tail) - st["end"]) >= silence_gap
        if not closed:
            break
        segments.append((st["start"], st["end"]))
        consumed = st["end"]
    return segments, consumed


def _worker_loop():
    global _committed
    while True:
        final = _stop_event.is_set()

        buf = audio.snapshot() if not final else _final_audio[0]
        if buf is not None:
            tail = buf[_committed:]
            min_tail = int(MIN_TAIL_S * audio.SAMPLE_RATE)
            if len(tail) >= min_tail or (final and len(tail) > 0):
                segments, consumed = _closed_segments(tail, final)
                for start, end in segments:
                    phrase = tail[start:end]
                    dur = len(phrase) / audio.SAMPLE_RATE
                    t0 = time.perf_counter()
                    # Prompt = personal vocabulary + recent transcript.
                    # The vocabulary biases Whisper toward the user's names
                    # and jargon; the transcript tail gives it sentence flow.
                    context = (vocab.whisper_prefix()
                               + " ".join(_texts)[-350:]).strip() or None
                    text = transcribe.run(phrase, initial_prompt=context)
                    if text.strip():
                        _texts.append(text.strip())
                    print(f"[stream] Phrase ({dur:.1f}s) transcribed "
                          f"in {time.perf_counter() - t0:.2f}s"
                          + (" [final]" if final else " [while speaking]"))
                _committed += consumed

        if final:
            return
        _wake.wait(POLL_INTERVAL_S)
        _wake.clear()


# Holder for the final full buffer, set by stop() before the worker's last pass.
_final_audio: list[np.ndarray | None] = [None]


# ── Public API ────────────────────────────────────────────────────────────────

def start():
    """Begin watching the live recording. Call right after audio.start_recording()."""
    global _worker, _committed
    _committed = 0
    _texts.clear()
    _final_audio[0] = None
    _stop_event.clear()
    _wake.clear()
    _worker = threading.Thread(target=_worker_loop, daemon=True)
    _worker.start()


def stop() -> str:
    """
    Stop the recording, transcribe whatever phrase is still open, and
    return the full raw transcript (empty string if no speech).
    """
    global _worker
    _final_audio[0] = audio.stop_recording_raw()
    _stop_event.set()
    _wake.set()
    if _worker is not None:
        _worker.join()
        _worker = None
    return " ".join(_texts).strip()
