"""
transcribe.py — Speech-to-Text via faster-whisper.

Responsibility: Accept a float32 NumPy audio array at 16 kHz and return
a raw transcript string (uncleaned — fillers intact).

Latency optimisations vs original:
  - beam_size reduced 5 → 1 (greedy decode — ~40% faster, minimal quality loss)
  - language pinned to "en" by default (skips language detection overhead ~200ms)
  - num_workers=2 so the model can process chunks in parallel
  - best_of=1, temperature=0 (pure greedy, no sampling fallback)
  - without_timestamps=True (skip timestamp computation)
"""

import os
import numpy as np
from faster_whisper import WhisperModel

# ── Configuration ─────────────────────────────────────────────────────────────

# large-v3-turbo gives Wispr-Flow-level accuracy. medium.en is faster but
# mishears too often — not worth the tradeoff.
# Override with: WISPR_WHISPER_MODEL=medium.en python main.py
MODEL_SIZE = os.getenv("WISPR_WHISPER_MODEL", "large-v3-turbo")

DEVICE       = "cpu"
COMPUTE_TYPE = "int8"   # int8 quantisation — fastest on CPU/Apple Silicon

# Pin to English for speed. Set to None for auto-detect (adds ~200ms).
LANGUAGE = "en"

# ── Lazy model loader ─────────────────────────────────────────────────────────

_model: WhisperModel | None = None

def _load_model() -> WhisperModel:
    """Load faster-whisper model on first call. Cached after that."""
    global _model
    if _model is None:
        print(f"[transcribe] Loading Whisper '{MODEL_SIZE}' — "
              "may download ~500 MB on first run …")
        _model = WhisperModel(
            MODEL_SIZE,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
            num_workers=2,   # parallel chunk processing for longer audio
        )
        print("[transcribe] Whisper ready.")
    return _model


# ── Public API ────────────────────────────────────────────────────────────────

def run(audio: np.ndarray) -> str:
    """
    Transcribe `audio` (float32, 16 kHz, mono) and return raw text.
    Returns an empty string if transcription yields nothing useful.
    """
    model = _load_model()

    segments, info = model.transcribe(
        audio,
        language=LANGUAGE,
        vad_filter=False,               # VAD already applied in audio.py
        beam_size=5,                    # restored for accuracy — beam_size=1 missed too many words
        best_of=1,
        temperature=0,
        condition_on_previous_text=False,
        word_timestamps=False,
        without_timestamps=True,        # still skip timestamps for speed
    )

    # Consume the generator — segments stream as they decode.
    parts = [seg.text for seg in segments]

    if not parts:
        return ""

    raw_text = " ".join(parts).strip()

    # Strip hallucinated noise tokens Whisper emits for non-speech audio.
    for token in ("[BLANK_AUDIO]", "(Music)", "[Music]", "(Silence)", "(Applause)"):
        raw_text = raw_text.replace(token, "").strip()

    print(f"[transcribe] Raw ({info.language}, "
          f"{info.language_probability:.0%}): {raw_text!r}")

    return raw_text
