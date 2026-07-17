# granite-local 🎙️

A fully local, IBM-powered AI voice dictation tool — hold to talk, release to paste.
**No cloud. No API keys. No subscriptions.** Runs entirely on your Mac using IBM Granite models.

```
[Hold Right-⌘] → Speak (phrases transcribe live) → Release → Polish → Paste ✓
```

While you talk, an **orange waveform pill** floats at the bottom of your screen,
reacting to your voice. Finished phrases are transcribed in the background
*while you're still speaking* — so when you release the key, only your last
phrase remains, and the text lands in ~1–3 seconds.

---

## IBM Stack

| Component | Model |
|-----------|-------|
| Speech-to-Text | `gabegoodhart/granite4.1-speech:2b` via Ollama |
| AI Text Polish | `gabegoodhart/granite4.1:3b` via Ollama |
| Voice Activity Detection | Silero VAD |
| Text Injection | macOS CGEvent (Cmd+V) |

Everything runs locally on your machine. No data leaves your computer.

---

## Architecture

```
Audio Capture       Streaming STT             AI Polish           Text Injection
(sounddevice        (granite4.1-speech,       (Ollama             (clipboard +
 + silero-vad)       phrase-by-phrase          granite4.1:3b)      CGEvent Cmd+V)
      │               while speaking)               │                    │
   [Stage 1]          [Stage 2]                 [Stage 3]           [Stage 4]
```

| File | Responsibility |
|------|----------------|
| `audio.py` | Mic capture + Silero VAD (segmentation + trimming) |
| `stream.py` | Streaming transcription — phrases transcribe while you speak |
| `transcribe.py` | IBM granite4.1-speech STT → raw transcript |
| `polish.py` | IBM granite4.1:3b → clean polished text |
| `inject.py` | Clipboard + CGEvent Cmd+V paste into any focused app |
| `overlay.py` | Overlay controller (talks to the pill subprocess) |
| `overlay_process.py` | The orange waveform pill (Cocoa/Core Animation) |
| `history.py` | Persistent dictation history (~/.wispr-local/history.jsonl) |
| `history_panel.py` | Floating history panel — click any entry to re-paste |
| `vocab.py` | Personal vocabulary loader |
| `learn.py` | Auto-learning — adds new words to vocabulary automatically |
| `main.py` | Hotkey listener + pipeline orchestration |

---

## Measured Latency (M1 MacBook, 16 GB)

Felt latency = key release → text pasted. Models warm (after first use).

| Dictation | STT | Polish | **Felt latency** |
|-----------|-----|--------|------------------|
| Short (~2s speech) | ~0.4s | ~0.6s | **~1.0–1.5s** |
| Long (~14s speech) | ~0.5s | ~1.5s | **~2.0–3.0s** |

Long dictations stay fast because phrases are transcribed while you're
still talking — when you release the key only the final phrase remains.

---

## Quick Setup (Automated)

Run the setup script — it handles everything:

```bash
cd granite-local
bash setup.sh
```

This installs Homebrew dependencies, creates a Python venv, installs all
packages, starts Ollama, and pulls both Granite models automatically.

Then start the app:

```bash
source venv/bin/activate
python main.py
```

---

## Manual Setup

### 1. Install Ollama + Granite Models

Download Ollama from **https://ollama.com**, then:

```bash
ollama serve &
ollama pull gabegoodhart/granite4.1-speech:2b   # ~2.3 GB — speech-to-text
ollama pull gabegoodhart/granite4.1:3b           # ~2.1 GB — text polish
```

### 2. Install System Dependencies

```bash
brew install portaudio    # required by sounddevice for mic access
```

### 3. Set Up Python Environment

```bash
cd granite-local
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Grant macOS Permissions

Grant each to **Terminal.app** (or whatever app you launch Python from):

1. **Microphone** — System Settings → Privacy & Security → Microphone
2. **Accessibility** — System Settings → Privacy & Security → Accessibility *(for Cmd+V paste)*
3. **Input Monitoring** — System Settings → Privacy & Security → Input Monitoring *(for global hotkey)*

macOS will prompt automatically on first run.

---

## Running

```bash
source venv/bin/activate
ollama serve &   # skip if already running
python main.py
```

On first run both Granite models warm up (~30–60s). Subsequent starts are fast.

**Using it:**
1. Click anywhere you want text to appear
2. **Hold Right-⌘** and speak — the orange waveform pill appears and reacts to your voice
3. **Release Right-⌘** — the pill ripples while it finishes up
4. Polished text appears at your cursor in ~1–3 seconds
5. **Tap Right-⌥ (Option)** to open the history panel and re-paste any previous dictation

---

## Customisation

### Change the hotkey
In `main.py`:
```python
HOTKEY = keyboard.Key.cmd_r   # Right-Cmd (default)
# HOTKEY = keyboard.Key.alt_r # Right-Alt alternative
```

### Personal vocabulary (names, jargon, products)
Edit `~/.wispr-local/vocabulary.txt` — one word or phrase per line. Every
dictation feeds this list to both the speech model and the polish LLM,
so names come out right. Changes apply on the next dictation — no restart needed.

**Auto-learning:** new out-of-vocabulary words that appear in 2 separate
dictations are added automatically (`learn.py`). One-off errors are ignored;
real names and jargon get learned. Tune with `PROMOTE_AFTER` in `learn.py`.

### Tune AI polish rules
Edit `SYSTEM_PROMPT` in `polish.py` — e.g. add personal snippet rules:
```
If the speaker says "calendar link", replace it with: https://calendly.com/yourname
```

### Tune streaming behaviour
In `stream.py`: `SILENCE_CLOSE_S` (how much silence closes a phrase) and
`POLL_INTERVAL_S` (how often the worker checks for new phrases).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'sounddevice'` | Run `pip install -r requirements.txt` inside the venv |
| `PortAudio not found` | `brew install portaudio` then reinstall sounddevice |
| `Ollama not reachable` | Run `ollama serve` in another terminal |
| Polish falls back to raw text | `ollama pull gabegoodhart/granite4.1:3b` |
| Transcription not working | `ollama pull gabegoodhart/granite4.1-speech:2b` |
| Text not pasting | Grant Accessibility permission to your terminal |
| Hotkey not detected | Grant Input Monitoring permission to your terminal |
| No waveform pill appears | Run `pip show pyobjc-framework-Cocoa` to confirm it installed |
| Model responds instead of cleaning | Already handled — app falls back to raw transcript automatically |

---

## Built with IBM Bob

This project was designed and built end-to-end with **[IBM Bob](https://www.ibm.com/products/bob)**, IBM's AI software engineering assistant.

Bob was used throughout the entire development lifecycle:

- **Architecture design** — Bob planned the 4-stage pipeline (audio capture → streaming STT → AI polish → text injection) and identified the phrase-by-phrase streaming approach that keeps felt latency under 3 seconds
- **Core implementation** — every file in this repo was written or significantly refactored with Bob: `audio.py`, `stream.py`, `transcribe.py`, `polish.py`, `inject.py`, `overlay.py`, `overlay_process.py`, `history.py`, `history_panel.py`, `vocab.py`, `learn.py`, `main.py`
- **IBM Granite integration** — Bob identified and integrated `gabegoodhart/granite4.1-speech:2b` (STT) and `gabegoodhart/granite4.1:3b` (text polish) as the full IBM stack, replacing earlier non-IBM model defaults
- **System prompt engineering** — Bob wrote and iteratively refined the `SYSTEM_PROMPT` in `polish.py` so the model cleans transcripts without answering questions or following instructions embedded in the dictated text
- **Response detection** — Bob designed the `_is_response()` detector that catches cases where the LLM replies conversationally instead of cleaning, falling back to the raw transcript automatically
- **Streaming architecture** — Bob designed the phrase-closing logic in `stream.py` so earlier phrases are transcribed while the user is still speaking, reducing key-release latency significantly
- **macOS overlay** — Bob built the Cocoa/Core Animation waveform pill in `overlay_process.py`: the capsule shape, live mic-reactive bars, traveling-wave animations for transcribing/polishing states, and the fade-in/out lifecycle
- **Codebase unification** — Bob merged two separate forks (wispr-local + granite-local) into one clean repo, removing all non-IBM model references and aligning everything to the IBM Granite stack
- **Debugging & fixes** — throughout the build Bob diagnosed and fixed issues: `keep_alive` silently failing on the OpenAI-compatible Ollama endpoint, Python 3.14 incompatibility with `pyobjc-core`, CGEvent paste reliability, and VAD silence threshold tuning
- **Documentation** — this README was written by Bob

> Bob runs locally inside IBM's developer tooling. No code or conversation left the IBM environment.
