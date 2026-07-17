"""
transcribe.py — Speech-to-Text: IBM granite4.1-speech (default) with mlx/cpu fallback.

Responsibility: Accept a float32 NumPy audio array at 16 kHz and return
a raw transcript string (uncleaned — fillers intact).

Backends:
  granite — IBM granite4.1-speech via Ollama. DEFAULT. Full IBM stack.
  mlx     — mlx-whisper on Apple Silicon GPU. Fallback or override.
  cpu     — faster-whisper (CTranslate2, int8). Fallback for Intel Macs.

Force one with WISPR_STT_BACKEND=granite|mlx|cpu.

`initial_prompt` lets the streaming layer pass already-transcribed text so
each phrase is decoded with the context of what came before — noticeably
better spelling/consistency for names and terminology.
"""

import os
import re
import numpy as np

# ── Backend selection ─────────────────────────────────────────────────────────

_FORCED = os.getenv("WISPR_STT_BACKEND", "").strip().lower()

# Default to granite (IBM stack). Fall back to mlx on Apple Silicon,
# then cpu if mlx is not available.
if _FORCED in ("granite", "mlx", "cpu"):
    BACKEND = _FORCED
else:
    BACKEND = "granite"   # IBM granite4.1-speech is the default

# ── Configuration ─────────────────────────────────────────────────────────────

# MLX fallback — only used if WISPR_STT_BACKEND=mlx is explicitly set.
MLX_MODEL = os.getenv(
    "WISPR_WHISPER_MODEL_MLX", "mlx-community/whisper-small.en-mlx")

# CPU fallback — only used if WISPR_STT_BACKEND=cpu is explicitly set.
CPU_MODEL = os.getenv("WISPR_WHISPER_MODEL", "distil-small.en")

# Pin to English for speed.
LANGUAGE = "en"

# Noise tokens the speech model may emit for non-speech audio.
_NOISE_TOKENS = ("[BLANK_AUDIO]", "(Music)", "[Music]", "(Silence)", "(Applause)")

# ── CPU fallback backend (faster-whisper) ─────────────────────────────────────

_cpu_model = None

def _load_cpu_model():
    global _cpu_model
    if _cpu_model is None:
        from faster_whisper import WhisperModel
        print(f"[transcribe] Loading CPU fallback model '{CPU_MODEL}' …")
        _cpu_model = WhisperModel(
            CPU_MODEL, device="cpu", compute_type="int8", num_workers=2)
        print("[transcribe] CPU model ready.")
    return _cpu_model


def _run_cpu(audio: np.ndarray, initial_prompt: str | None) -> str:
    segments, info = _load_cpu_model().transcribe(
        audio,
        language=LANGUAGE,
        vad_filter=False,               # VAD already applied in audio.py
        beam_size=5,
        best_of=1,
        temperature=0,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
        word_timestamps=False,
        without_timestamps=True,
    )
    return " ".join(seg.text for seg in segments).strip()


# ── MLX backend (Apple GPU) ───────────────────────────────────────────────────

def _run_mlx(audio: np.ndarray, initial_prompt: str | None) -> str:
    import mlx_whisper
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MLX_MODEL,
        language=LANGUAGE,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
        word_timestamps=False,
        fp16=True,
    )
    return result["text"].strip()


# ── Granite speech backend (Ollama) — DEFAULT ─────────────────────────────────

def run(audio: np.ndarray, initial_prompt: str | None = None) -> str:
    """
    Transcribe `audio` (float32, 16 kHz, mono) and return raw text.
    Returns an empty string if transcription yields nothing useful.

    `initial_prompt` — optional preceding transcript for context.
    """
    if BACKEND == "mlx":
        raw_text = _run_mlx(audio, initial_prompt)
    else:
        raw_text = _run_cpu(audio, initial_prompt)

    for token in _NOISE_TOKENS:
        raw_text = raw_text.replace(token, "").strip()

    print(f"[transcribe] Raw ({BACKEND}): {raw_text!r}")
    return raw_text
