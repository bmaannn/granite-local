"""
learn.py — Automatic vocabulary learning from dictations.

After each dictation, scans the polished text for out-of-vocabulary words
(not in the system English dictionary at /usr/share/dict/words). A word is
NOT learned on first sight — it becomes a candidate, and is promoted into
~/.wispr-local/vocabulary.txt only after appearing in PROMOTE_AFTER separate
dictations. This avoids the feedback loop where a one-off transcription
error gets learned and then biases every future dictation toward the error;
real names and jargon recur, mishears usually don't.

Candidates are tracked in ~/.wispr-local/vocab_candidates.json.
"""

import json
import os
import re
import time

import vocab

CANDIDATES_PATH = os.path.expanduser("~/.wispr-local/vocab_candidates.json")

# Promote a word to the vocabulary after it appears in this many dictations.
PROMOTE_AFTER = 2

# Ignore tokens shorter than this (initials, "ok", etc.).
MIN_LEN = 3

# Informal speech that's out-of-dictionary but not worth learning.
_STOPLIST = {
    "gonna", "wanna", "gotta", "kinda", "sorta", "dunno", "lemme",
    "gimme", "cuz", "coz", "yeah", "yep", "nope", "okay", "ok", "hmm",
}

MAX_CANDIDATES = 200      # oldest candidates are dropped past this

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*[A-Za-z]")

# ── System dictionary ─────────────────────────────────────────────────────────

_sys_words: set[str] | None = None

def _system_words() -> set[str]:
    global _sys_words
    if _sys_words is None:
        try:
            with open("/usr/share/dict/words", "r", encoding="utf-8") as f:
                _sys_words = {line.strip().lower() for line in f}
        except OSError:
            _sys_words = set()   # no system dict — learning disabled
    return _sys_words


# ── Candidate store ───────────────────────────────────────────────────────────

def _load_candidates() -> dict:
    if not os.path.exists(CANDIDATES_PATH):
        return {}
    try:
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_candidates(cands: dict):
    if len(cands) > MAX_CANDIDATES:
        # Drop the least recently seen candidates.
        keep = sorted(cands.items(), key=lambda kv: kv[1]["last"],
                      reverse=True)[:MAX_CANDIDATES]
        cands = dict(keep)
    os.makedirs(os.path.dirname(CANDIDATES_PATH), exist_ok=True)
    tmp = CANDIDATES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CANDIDATES_PATH)


# ── Public API ────────────────────────────────────────────────────────────────

def observe(text: str) -> list[str]:
    """
    Scan one dictation's polished text; update candidate counts and promote
    recurring out-of-vocabulary words into the vocabulary file.

    Returns the list of newly learned words (usually empty).
    """
    sysdict = _system_words()
    if not sysdict:
        return []

    known = {w.lower() for w in vocab.words()}
    found: dict[str, str] = {}   # lowercase → surface form from this text

    for match in _WORD_RE.finditer(text):
        token = match.group()
        low = token.lower().replace("'s", "")
        if (len(low) < MIN_LEN or low in _STOPLIST or low in known
                or low in sysdict):
            continue
        # Prefer a capitalized surface form if any occurrence had one
        # (likely a name — that's the casing worth remembering).
        if low not in found or token[0].isupper():
            found[low] = token

    if not found:
        return []

    cands = _load_candidates()
    learned = []
    now = time.time()

    for low, form in found.items():
        entry = cands.get(low, {"count": 0, "form": form, "last": now})
        entry["count"] += 1
        entry["last"] = now
        if form[0].isupper():
            entry["form"] = form

        if entry["count"] >= PROMOTE_AFTER:
            _add_to_vocabulary(entry["form"])
            learned.append(entry["form"])
            cands.pop(low, None)
        else:
            cands[low] = entry

    _save_candidates(cands)

    for word in learned:
        print(f"[vocab] Learned new word: {word!r} "
              f"(seen in {PROMOTE_AFTER} dictations — added to vocabulary)")
    return learned


def _add_to_vocabulary(word: str):
    """Append a word to vocabulary.txt (vocab.py picks it up via mtime)."""
    vocab.words()   # ensures the file exists
    with open(vocab.PATH, "a", encoding="utf-8") as f:
        f.write(word + "\n")
