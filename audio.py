"""
audio.py — Microphone capture with Silero VAD gate.

Responsibility: Record audio from the default microphone for the duration
the hotkey is held, apply a lightweight Voice Activity Detection pass to
trim leading/trailing silence, and return a float32 NumPy array at 16 kHz
ready for granite4.1-speech transcription.

Uses the `silero-vad` pip package for voice activity detection.
"""

import threading
import numpy as np
import sounddevice as sd
import torch
from silero_vad import load_silero_vad, get_speech_timestamps

# ── Constants ────────────────────────────────────────────────────────────────

SAMPLE_RATE = 16_000        # granite4.1-speech expects 16 kHz mono
CHANNELS    = 1             # Mono
DTYPE       = "float32"     # sounddevice native float

# VAD threshold: speech frames with confidence above this are kept.
# Lower → more sensitive (may include noise); higher → may clip soft speech.
VAD_THRESHOLD = 0.4

# Minimum speech duration (seconds) to consider valid after VAD trim.
# Prevents a click or breath from firing the pipeline.
MIN_SPEECH_DURATION = 0.3

# ── Silero VAD loader ─────────────────────────────────────────────────────────

_vad_model = None

def _load_vad():
    """Lazy-load Silero VAD from pip package (cached after first call)."""
    global _vad_model
    if _vad_model is None:
        # load_silero_vad() comes from the `silero-vad` pip package.
        # Downloads ~2 MB ONNX model on first call, cached in ~/.cache.
        _vad_model = load_silero_vad()
    return _vad_model


# ── Volume level callback ─────────────────────────────────────────────────────

# External code can set this to a callable(float) to receive RMS level
# updates in real time while recording. Values range 0.0 → 1.0.
on_level: callable = None


# ── Internal recording state ──────────────────────────────────────────────────

class _Recorder:
    """Thread-safe ring buffer that sounddevice writes into via callback."""

    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def start(self):
        self._chunks.clear()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=512,
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata: np.ndarray, frames: int, time, status):
        if status:
            print(f"[audio] sounddevice status: {status}")
        chunk = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(chunk)

        # Compute RMS level and fire the callback if registered.
        if on_level is not None:
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            # Normalise: typical speech peaks ~0.1–0.3, clamp to 0–1.
            level = min(1.0, rms / 0.15)
            on_level(level)

    def stop(self) -> np.ndarray | None:
        """Stop recording and return concatenated float32 audio, or None."""
        if self._stream is None:
            return None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._chunks:
                return None
            return np.concatenate(self._chunks)

    def snapshot(self) -> np.ndarray | None:
        """Concatenated copy of everything captured so far, without stopping."""
        with self._lock:
            if not self._chunks:
                return None
            return np.concatenate(self._chunks)


_recorder = _Recorder()


# ── Public API ────────────────────────────────────────────────────────────────

def start_recording():
    """Begin capturing microphone audio. Called on hotkey press."""
    _recorder.start()


def stop_recording() -> np.ndarray | None:
    """
    Stop capturing and return VAD-trimmed audio ready for transcription.

    Returns None if no speech was detected or the recording was too short.
    """
    raw = _recorder.stop()
    if raw is None or len(raw) == 0:
        return None

    trimmed = _vad_trim(raw)
    if trimmed is None:
        print("[audio] VAD: no speech detected, discarding.")
        return None

    duration = len(trimmed) / SAMPLE_RATE
    if duration < MIN_SPEECH_DURATION:
        print(f"[audio] VAD: speech too short ({duration:.2f}s), discarding.")
        return None

    print(f"[audio] Captured {duration:.2f}s of speech.")
    return trimmed


def stop_recording_raw() -> np.ndarray | None:
    """Stop capturing and return the raw untrimmed audio (streaming mode)."""
    return _recorder.stop()


def snapshot() -> np.ndarray | None:
    """Copy of all audio captured so far, without stopping (streaming mode)."""
    return _recorder.snapshot()


def vad_segments(audio: np.ndarray) -> list[dict]:
    """
    Run Silero VAD on `audio` and return speech segments as a list of
    {"start": sample, "end": sample} dicts (empty list if no speech).
    """
    model = _load_vad()
    return get_speech_timestamps(
        torch.from_numpy(audio),
        model,
        sampling_rate=SAMPLE_RATE,
        threshold=VAD_THRESHOLD,
        min_speech_duration_ms=int(MIN_SPEECH_DURATION * 1000),
        min_silence_duration_ms=200,
        speech_pad_ms=100,   # keep a little context so word onsets aren't clipped
    )


# ── VAD trim ─────────────────────────────────────────────────────────────────

def _vad_trim(audio: np.ndarray) -> np.ndarray | None:
    """
    Run Silero VAD and return only the speech segment, trimming silence.

    Input must be a 1-D float32 NumPy array at 16 kHz.
    """
    speech_timestamps = vad_segments(audio)
    if not speech_timestamps:
        return None

    # Slice from the start of the first speech segment to the end of the last.
    start = speech_timestamps[0]["start"]
    end   = speech_timestamps[-1]["end"]
    return audio[start:end]
