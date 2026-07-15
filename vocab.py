"""
vocab.py — Personal vocabulary for names, jargon, and product terms.

Whisper guesses unknown words phonetically ("Basith" → "Bassett"), and the
polish LLM can't fix what it doesn't know about. This module maintains a
user-editable dictionary that gets injected into BOTH stages:

  - transcribe: as part of Whisper's initial_prompt (biases decoding toward
    these words — the standard way to teach Whisper custom vocabulary)
  - polish: as a correction list (fixes near-phonetic misses that slipped
    through, e.g. "Basit" → "Basith")

Edit ~/.wispr-local/vocabulary.txt — one word or phrase per line. Changes
apply on the next dictation; no restart needed (file mtime is checked).
"""

import os

PATH = os.path.expanduser("~/.wispr-local/vocabulary.txt")

_TEMPLATE = """\
# wispr-local personal vocabulary
#
# One word or phrase per line: names, companies, products, jargon —
# anything the transcriber keeps getting wrong.
# Lines starting with # are ignored. Changes apply on the next dictation.
Basith
"""

_cache = {"mtime": None, "words": []}


def words() -> list[str]:
    """Current vocabulary, freshly reloaded whenever the file changes."""
    if not os.path.exists(PATH):
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(_TEMPLATE)

    mtime = os.path.getmtime(PATH)
    if _cache["mtime"] != mtime:
        parsed = []
        with open(PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parsed.append(line)
        _cache["mtime"] = mtime
        _cache["words"] = parsed
    return _cache["words"]


# Whisper's prompt window is small (~224 tokens) and shared with the rolling
# transcript context — cap how many vocabulary entries we send (newest last
# in the file are most recently learned, so keep those).
MAX_WHISPER_WORDS = 50


def whisper_prefix() -> str:
    """Vocabulary as a Whisper initial_prompt prefix ('' if empty)."""
    w = words()[-MAX_WHISPER_WORDS:]
    return f"Glossary: {', '.join(w)}. " if w else ""


def polish_section() -> str:
    """Vocabulary as an extra system-prompt section for polish ('' if empty)."""
    w = words()
    if not w:
        return ""
    return (
        "\n\nPERSONAL VOCABULARY (correct spellings the speaker uses): "
        + ", ".join(w)
        + "\nThe transcription may misspell these phonetically. If a word in "
        "the text is a close phonetic match to one of these, replace it with "
        "the correct spelling from the vocabulary. Do not force these words "
        "in where they were not spoken."
    )
