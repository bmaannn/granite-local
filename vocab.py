"""
vocab.py — Personal vocabulary for names, jargon, and product terms.

granite4.1-speech can mishear unknown words phonetically ("Basith" → "Bassett"),
and the polish LLM can't fix what it doesn't know about. This module maintains a
user-editable dictionary that gets injected into BOTH stages:

  - transcribe: as an initial_prompt prefix (biases decoding toward these words)
  - polish: as a correction list (fixes near-phonetic misses that slipped through)

Edit ~/.wispr-local/vocabulary.txt — one word or phrase per line. Changes
apply on the next dictation; no restart needed (file mtime is checked).
"""

import os

PATH = os.path.expanduser("~/.wispr-local/vocabulary.txt")

_TEMPLATE = """\
# granite-local personal vocabulary
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


# The speech model's prompt window is small — cap how many vocabulary entries
# we send (newest entries in the file are kept).
MAX_VOCAB_WORDS = 50


def speech_prompt_prefix() -> str:
    """Vocabulary as an initial_prompt prefix for the speech model ('' if empty)."""
    w = words()[-MAX_VOCAB_WORDS:]
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
