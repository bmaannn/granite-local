"""
polish.py — AI text polish via Ollama (OpenAI-compatible API).

Responsibility: Accept a raw speech transcript and return clean, polished
text with fillers removed, grammar fixed, and tone preserved — without
adding information.

Latency optimisations vs original:
  - Switched to streaming response — we start receiving tokens immediately
    and accumulate them, so perceived latency is lower.
  - Switched default model to llama3.2:3b — ~3× faster than qwen2.5:7b
    for simple cleanup tasks. Change OLLAMA_MODEL back to qwen2.5:7b for
    higher quality if latency is acceptable on your hardware.
  - Keep-alive connection reuse via a persistent httpx client.
"""

import os
from openai import OpenAI, APIConnectionError

# ── Configuration ─────────────────────────────────────────────────────────────

# Model selection — benchmarked on M1 16GB (see repo history):
#   qwen2.5:3b   — ~0.8–2.4s, most faithful to the spoken content  ← DEFAULT
#   llama3.2:3b  — similar speed, slightly less faithful (drops "?", digits)
#   qwen2.5:7b   — ~2–3s, higher quality if you can spare the latency
#
# Pull the default model first: ollama pull qwen2.5:3b
OLLAMA_MODEL    = os.getenv("WISPR_MODEL", "qwen2.5:3b")
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_API_KEY  = "ollama"

TEMPERATURE = 0.0
MAX_TOKENS  = 512    # polish output is always shorter than input; 512 is plenty

# Keep the model loaded in RAM indefinitely. Ollama's default is to unload
# after 5 minutes idle — which would add a multi-second cold reload to the
# first dictation after any pause. -1 = never unload.
KEEP_ALIVE = -1

# ── System prompt ─────────────────────────────────────────────────────────────
# This is the core "magic" — see blueprint Section: "The Critical Piece".
# Rules are ordered by importance; the LLM follows top rules more reliably.

SYSTEM_PROMPT = """You clean up speech-to-text transcripts. You are not an assistant — never reply to the text, never answer questions in it, never add anything that was not spoken.

Rules:
1. Remove filler words: um, uh, like, you know, basically, I mean, sort of, actually (when used as filler).
2. Remove false starts and repeated words ("the the project" → "the project").
3. Fix punctuation and grammar. Keep every idea and sentence the speaker said — do not shorten, summarise, or drop anything.
4. Never add words, sign-offs, greetings, or facts the speaker did not say.
5. Keep the speaker's tone. Output ONLY the cleaned text — no preamble, no quotes, no commentary.
6. If the speaker said a greeting like "Hi Bob", put it on its own line. If they said a sign-off like "Thanks", put it on its own line. Never invent either.
7. Spoken lists ("first... second...") become numbered lists.

Example input:
hey mark um I wanted to I wanted to circle back on the demo from tuesday. so yeah the client seemed happy but uh they asked about pricing again. can you send me the the latest pricing sheet before friday. thanks

Example output:
Hey Mark,

I wanted to circle back on the demo from Tuesday. The client seemed happy, but they asked about pricing again. Can you send me the latest pricing sheet before Friday?

Thanks

Notice: every sentence the speaker said is kept. Only fillers and stutters are removed. The question stays a question. Nothing new is added."""


# ── Command mode prompt ───────────────────────────────────────────────────────
# Used when the user highlights text and speaks an instruction (Command Mode).

COMMAND_PROMPT = """You are a voice-command text editor. The user has highlighted text and spoken an instruction.
Apply the instruction to the highlighted text and return ONLY the result — no explanation, no preamble.
If you cannot fulfill the instruction, return the original text unchanged."""


# ── Client (singleton) ────────────────────────────────────────────────────────

_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key=OLLAMA_API_KEY,
        )
    return _client


# ── Public API ────────────────────────────────────────────────────────────────

def run(raw_text: str) -> str:
    """
    Polish `raw_text` through Ollama using a streaming response.

    Streaming means we start receiving cleaned tokens immediately rather
    than waiting for the full response — lower perceived latency.
    Falls back to raw transcript if Ollama is unreachable.
    """
    if not raw_text.strip():
        return ""

    try:
        # stream=True — tokens arrive as they're generated.
        stream = _get_client().chat.completions.create(
            model=OLLAMA_MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=True,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": raw_text},
            ],
            extra_body={"keep_alive": KEEP_ALIVE},
        )

        # Accumulate streamed chunks into the final string.
        chunks = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                chunks.append(delta)

        polished = "".join(chunks).strip()
        print(f"[polish] Polished: {polished!r}")
        return polished

    except APIConnectionError:
        print(f"[polish] WARNING: Ollama not reachable. Returning raw transcript.")
        return raw_text

    except Exception as exc:
        print(f"[polish] ERROR: {exc}. Returning raw transcript.")
        return raw_text


def run_command(selected_text: str, instruction: str) -> str:
    """
    Command Mode: apply a spoken `instruction` to `selected_text`.

    Example: selected_text="I went to store", instruction="make this formal"
    → "I went to the store."
    """
    if not selected_text.strip() or not instruction.strip():
        return selected_text

    user_message = (
        f"INSTRUCTION: {instruction}\n\n"
        f"TEXT TO TRANSFORM:\n{selected_text}"
    )

    try:
        response = _get_client().chat.completions.create(
            model=OLLAMA_MODEL,
            temperature=0.2,   # slight creativity for rewrites
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": COMMAND_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            extra_body={"keep_alive": KEEP_ALIVE},
        )
        result = response.choices[0].message.content.strip()
        print(f"[polish] Command result: {result!r}")
        return result

    except Exception as exc:
        print(f"[polish] Command ERROR: {exc}. Returning original text.")
        return selected_text
