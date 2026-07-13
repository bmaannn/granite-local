# wispr-local 🎙️

A fully local Wispr Flow clone — hold-to-talk AI dictation that works in every app.  
**No cloud. No API keys. No subscriptions.** Runs entirely on your Mac.

```
[Hold Right-⌘] → Record → Release → Transcribe → Polish → Paste ✓
```

---

## Architecture

```
Audio Capture    Speech-to-Text       AI Polish           Text Injection
(sounddevice     (faster-whisper      (Ollama LLM         (pyperclip +
 + silero-vad)    large-v3-turbo)      qwen2.5:7b)         pyautogui Cmd+V)
      │                  │                  │                    │
   [Stage 1]          [Stage 2]          [Stage 3]           [Stage 4]
```

| File | Responsibility |
|------|---------------|
| `audio.py` | Mic capture + Silero VAD silence trimming |
| `transcribe.py` | faster-whisper STT → raw transcript |
| `polish.py` | Ollama LLM → clean polished text |
| `inject.py` | Clipboard paste into any focused app |
| `main.py` | Hotkey listener + pipeline orchestration |

---

## Latency Benchmarks

End-to-end time from key release to text appearing (5–10s of speech):

| Hardware | Whisper | Ollama Polish | **Total** |
|----------|---------|---------------|-----------|
| M3 Pro / Max (36 GB+) | ~0.3–0.6s | ~0.4–0.8s | **~0.7–1.5s** ✅ |
| M2 MacBook Pro (16 GB) | ~0.5–1.0s | ~0.8–1.5s | **~1.3–2.5s** ✅ |
| M1 MacBook Air (8 GB) | ~1.0–1.8s | ~1.5–3.0s | **~2.5–5.0s** ⚠️ |
| Intel Mac (16 GB) | ~3–6s | ~4–8s | **~7–14s** ❌ |

> **Tip for slow hardware:** In `transcribe.py` change `MODEL_SIZE = "medium.en"` and in `polish.py` change `OLLAMA_MODEL = "llama3.2:3b"` to cut total latency by ~60%.

---

## Prerequisites

### 1. Install Ollama

Download from **https://ollama.com** and install. Then pull your model:

```bash
# Start the Ollama background server
ollama serve &

# Pull the AI polish model (4.4 GB download, one-time)
ollama pull qwen2.5:7b

# Verify it works
ollama run qwen2.5:7b "Say hello"
```

> Alternative models — edit `OLLAMA_MODEL` in `polish.py`:
> - `llama3.1:8b` — slightly higher quality
> - `llama3.2:3b` — fastest, good for M1 Air
> - `phi4:14b` — best quality, needs 16 GB+ RAM

---

### 2. Install Homebrew System Dependencies

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# PortAudio — required by sounddevice for low-latency mic access
brew install portaudio

# FFmpeg — required by faster-whisper for audio decoding
brew install ffmpeg
```

---

### 3. Set Up Python Environment

```bash
cd ~/Desktop/wispr-local

# Create isolated virtual environment (Python 3.11+ recommended)
python3 -m venv venv
source venv/bin/activate

# Install all dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

> **Apple Silicon note:** PyTorch will use MPS (Metal Performance Shaders)
> automatically for faster inference. No extra steps needed.

---

### 4. Grant macOS Permissions

This app needs **three permissions**. Grant each to **Terminal.app** (or
whatever app you launch Python from):

1. **Microphone**  
   System Settings → Privacy & Security → Microphone → ✅ Terminal

2. **Accessibility** *(required for pyautogui to simulate Cmd+V)*  
   System Settings → Privacy & Security → Accessibility → ✅ Terminal

3. **Input Monitoring** *(required for pynput global hotkey listener)*  
   System Settings → Privacy & Security → Input Monitoring → ✅ Terminal

> If you use VS Code, iTerm2, or another terminal, grant the permissions to
> that app instead. macOS may prompt you automatically on first run.

---

## Running

```bash
# Make sure you're in the venv and Ollama is running
source venv/bin/activate
ollama serve &   # skip if already running

# Launch wispr-local
python main.py
```

On first run, the Whisper model downloads (~1.5 GB for large-v3-turbo) and
loads into memory. Subsequent runs start in ~2–5 seconds.

**Using it:**
1. Click anywhere you want text to appear (email, Slack, Notes, any text field)
2. **Hold Right-⌘** and speak naturally
3. **Release Right-⌘** — watch the terminal for status
4. Polished text appears at your cursor within 1–5 seconds
5. **Ctrl+C** in the terminal to quit

---

## Customisation

### Change the hotkey
In `main.py`, edit:
```python
HOTKEY = keyboard.Key.cmd_r   # Right-Cmd (default)
# HOTKEY = keyboard.Key.alt_r # Right-Alt alternative
# HOTKEY = keyboard.Key.f13   # F13 if you have a full keyboard
```

### Tune AI polish rules
In `polish.py`, edit `SYSTEM_PROMPT` to add personal rules:
```
Always use em dashes instead of commas for asides.
Never use the word "utilize" — use "use" instead.
Always spell "Salesforce" with a capital S and F.
```

### Add snippet shortcuts
In `polish.py` `SYSTEM_PROMPT`, add:
```
If the user says "calendar link", replace it with: https://calendly.com/yourname
If the user says "my email", replace it with: you@company.com
```

### Switch to English-only (faster)
In `transcribe.py`:
```python
MODEL_SIZE = "medium.en"   # ~40% faster, English only
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'sounddevice'` | Run `pip install -r requirements.txt` inside the venv |
| `PortAudio not found` | Run `brew install portaudio` then re-install sounddevice |
| `Ollama not reachable` | Run `ollama serve` in a separate terminal tab |
| `Model not found` | Run `ollama pull qwen2.5:7b` |
| Text not pasting | Grant Accessibility permission to Terminal in System Settings |
| Hotkey not detected | Grant Input Monitoring permission to Terminal |
| Microphone not recording | Grant Microphone permission to Terminal |
| Whisper taking >10s | Switch to `medium.en` in `transcribe.py` |
| `BLANK_AUDIO` in output | Speak louder / closer to mic; check mic input in System Settings |

---

## Project Structure

```
wispr-local/
├── main.py          # Pipeline orchestrator + hotkey listener
├── audio.py         # Mic capture + Silero VAD silence trimming
├── transcribe.py    # faster-whisper speech-to-text
├── polish.py        # Ollama LLM text polishing
├── inject.py        # Clipboard paste text injection
├── requirements.txt # Python dependencies
└── README.md        # This file
```

---

## How It Works (Technical Summary)

1. **Hold Right-⌘** → `pynput` fires `on_press` → `audio.start_recording()` opens a `sounddevice.InputStream`
2. **Release Right-⌘** → `audio.stop_recording()` closes the stream, runs Silero VAD to trim silence, returns a `float32` NumPy array at 16 kHz
3. **`transcribe.run(audio)`** → `faster-whisper` transcribes to raw text (fillers, stammers intact)
4. **`polish.run(raw_text)`** → Ollama's `/v1/chat/completions` endpoint (same as OpenAI API) removes fillers, fixes grammar, preserves tone
5. **`inject.paste(polished_text)`** → saves clipboard, writes text, simulates `Cmd+V`, restores clipboard
