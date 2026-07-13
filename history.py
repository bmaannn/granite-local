"""
history.py — Persistent dictation history.

Every successful dictation is appended to ~/.wispr-local/history.jsonl:
one JSON object per line with {ts, raw, text}. Capped at MAX_ENTRIES.

Also usable as a CLI viewer:
    python3 history.py        # show last 20 dictations
    python3 history.py 50     # show last 50
"""

import json
import os
import sys
import time

DIR  = os.path.expanduser("~/.wispr-local")
PATH = os.path.join(DIR, "history.jsonl")

MAX_ENTRIES = 500


def load(limit: int | None = None) -> list[dict]:
    """Return history entries oldest-first (each: {ts, raw, text})."""
    if not os.path.exists(PATH):
        return []
    entries = []
    with open(PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a corrupt line rather than losing everything
    return entries[-limit:] if limit else entries


def add(raw: str, text: str) -> None:
    """Append a dictation. Rewrites the file when over the cap."""
    os.makedirs(DIR, exist_ok=True)
    entries = load()
    entries.append({"ts": time.time(), "raw": raw, "text": text})
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, PATH)


def format_ts(ts: float) -> str:
    """'Today 2:41 PM' / 'Yesterday 9:02 AM' / 'Jul 11, 3:15 PM'."""
    lt, now = time.localtime(ts), time.localtime()
    clock = time.strftime("%-I:%M %p", lt)
    if lt.tm_yday == now.tm_yday and lt.tm_year == now.tm_year:
        return f"Today {clock}"
    if lt.tm_yday == now.tm_yday - 1 and lt.tm_year == now.tm_year:
        return f"Yesterday {clock}"
    return time.strftime("%b %-d, ", lt) + clock


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    entries = load(limit=n)
    if not entries:
        print("No dictations yet.")
    for e in reversed(entries):
        print(f"── {format_ts(e['ts'])} " + "─" * 40)
        print(e["text"])
        print()
