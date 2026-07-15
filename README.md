# wispr-local 🎙️

A fully local Wispr Flow clone — hold-to-talk AI dictation that works in every app.
**No cloud. No API keys. No subscriptions.** Runs entirely on your Mac.

```
[Hold Right-⌘] → Speak (phrases transcribe live) → Release → Polish → Paste ✓
```

While you talk, a Wispr-style **orange waveform pill** floats at the bottom of
your screen, reacting to your voice. Finished phrases are transcribed in the
background *while you're still speaking* — so when you release the key, only
your last phrase remains, and the text lands in ~1–3 seconds.

---

## Architecture

```
Audio Capture       Streaming STT          AI Polish           Text Injection
(sounddevice        (faster-whisper,       (Ollama LLM         (clipboard +
 + silero-vad)       phrase-by-phrase       qwen2.5:3b)         CGEvent Cmd+V)
      │               while speaking)           │                    │
   [Stage 1]          [Stage 2]              [Stage 3]           [Stage 4]
```

| File | Responsibility |
|------|---------------|
| `audio.py` | Mic capture + Silero VAD (segmentation + trimming) |
| `stream.py` | Streaming transcription — phrases transcribe while you speak |
| `transcribe.py` | faster-whisper STT → raw transcript |
| `polish.py` | Ollama LLM → clean polished text |
| `inject.py` | Clipboard + CGEvent Cmd+V paste into any focused app |
| `overlay.py` | Overlay controller (talks to the pill subprocess) |
| `overlay_process.py` | The orange waveform pill (Cocoa/Core Animation) |
| `main.py` | Hotkey listener + pipeline orchestration |

---

## Measured Latency (M1 MacBook, 16 GB)

Felt latency = key release → text pasted. Models warm (after first use).
Default backend on Apple Silicon is **mlx-whisper `large-v3-turbo` on the GPU** —
the most accurate Whisper, at interactive speed.

| Dictation | STT drain | Polish | **Felt latency** |
|-----------|-----------|--------|------------------|
| Short (~2s speech) | ~1.7s | ~0.8s | **~2.4s** |
| Long (~14s speech) | ~2.0s | ~2.3s | **~4.3s** |

Long dictations stay fast because phrases are transcribed while you're
still talking; each phrase is decoded with the transcript so far as context.

**Whisper backend benchmark** (same machine, 2.3s / 14.3s of speech):

| Backend / model | Short | Long | Notes |
|-------|-------|------|-------|
| **MLX `large-v3-turbo` (GPU)** | 1.5s | 2.0s | **default** — best accuracy |
| MLX `small.en` (GPU) | 0.4s | 1.2s | `WISPR_WHISPER_MODEL_MLX=mlx-community/whisper-small.en-mlx` |
| CPU `distil-small.en` | 1.1s | 1.5s | `WISPR_STT_BACKEND=cpu` — fastest-feel option |
| CPU `base.en` | 0.5s | 1.3s | `WISPR_STT_BACKEND=cpu WISPR_WHISPER_MODEL=base.en` |
| CPU `large-v3-turbo` | 4.1s | 5.1s | don't — use the MLX backend instead |

---

## Prerequisites

### 1. Install Ollama

Download from **https://ollama.com** and install. Then pull the polish model:

```bash
ollama serve &            # start the background server (skip if running)
ollama pull qwen2.5:3b    # ~2 GB download, one-time
```

> Alternative models — set `WISPR_MODEL` or edit `polish.py`:
> - `llama3.2:3b` — similar speed, slightly less faithful
> - `qwen2.5:7b` — higher quality if you can spare ~1s extra latency

### 2. Install Homebrew System Dependencies

```bash
brew install portaudio    # required by sounddevice for mic access
```

### 3. Set Up Python Environment

```bash
cd wispr-local
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Grant macOS Permissions

Grant each to **Terminal.app** (or whatever app you launch Python from):

1. **Microphone** — System Settings → Privacy & Security → Microphone
2. **Accessibility** — System Settings → Privacy & Security → Accessibility *(for the Cmd+V paste)*
3. **Input Monitoring** — System Settings → Privacy & Security → Input Monitoring *(for the global hotkey)*

macOS usually prompts automatically on first run.

---

## Running

```bash
source venv/bin/activate
ollama serve &   # skip if already running
python main.py
```

On first run the Whisper model downloads (~500 MB for distil-small.en) and both
models warm up (~30–60s). Subsequent dictations are fast.

**Using it:**
1. Click anywhere you want text to appear
2. **Hold Right-⌘** and speak — the orange waveform pill appears and reacts to your voice
3. **Release Right-⌘** — the pill ripples while it finishes up
4. Polished text appears at your cursor in ~1–3 seconds

---

## Customisation

### Change the hotkey
In `main.py`:
```python
HOTKEY = keyboard.Key.cmd_r   # Right-Cmd (default)
# HOTKEY = keyboard.Key.alt_r # Right-Alt alternative
```

### Swap models (no code edits)
```bash
WISPR_WHISPER_MODEL=base.en WISPR_MODEL=qwen2.5:7b python main.py
```

### Personal vocabulary (names, jargon, products)
Edit `~/.wispr-local/vocabulary.txt` — one word or phrase per line. Every
dictation feeds this list to both Whisper (recognition bias) and the polish
LLM (phonetic correction), so names like "Basith" come out right. Changes
apply on the next dictation — no restart needed.

**Auto-learning:** new out-of-dictionary words that appear in 2 separate
dictations are added to the vocabulary automatically (`learn.py`). One-off
transcription errors don't recur, so they never get learned; real names and
jargon do. Tune with `PROMOTE_AFTER` in `learn.py`.

### Tune AI polish rules
Edit `SYSTEM_PROMPT` in `polish.py` — e.g. add personal snippet rules:
```
If the speaker says "calendar link", replace it with: https://calendly.com/yourname
```

### Tune streaming behaviour
In `stream.py`: `SILENCE_CLOSE_S` (how much silence "closes" a phrase) and
`POLL_INTERVAL_S` (how often the worker checks for new phrases).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'sounddevice'` | Run `pip install -r requirements.txt` inside the venv |
| `PortAudio not found` | `brew install portaudio` then reinstall sounddevice |
| `Ollama not reachable` | Run `ollama serve` in another terminal |
| Polish falls back to raw text | `ollama pull qwen2.5:3b` |
| Text not pasting | Grant Accessibility permission to your terminal |
| Hotkey not detected | Grant Input Monitoring permission to your terminal |
| No waveform pill appears | Check `pip show pyobjc-framework-Cocoa` installed cleanly |
| Transcription inaccurate | Try `WISPR_WHISPER_MODEL=small.en` (or `large-v3-turbo` on M-series Pro/Max) |
