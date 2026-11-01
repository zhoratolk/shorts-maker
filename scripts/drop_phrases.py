"""Which words were on screen when viewers left.

retention.py already finds where each clip loses its audience - the steepest
inter-slice drop, as a fraction of the clip's length. It never says what was
being said at that moment, so a drop at 0.34 stays a number nobody can act on.
This joins the drop to the clip's own word timeline (the `_words.json` written
at make-shorts time) and names the phrase.

Borrowed from manga-shorts' evening report (`mshorts/daily_report.py`), where the
same join is what turned "everyone leaves at 4-9 s" into "everyone leaves on the
biography line". For a stream clip the question is the same: on which sentence?
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# A viewer who swipes is reacting to what they just heard, not to what comes
# next, so the phrase is the stretch leading up to the drop, ending on the word
# being spoken at that second.
PHRASE_WINDOW_SECONDS = 2.5


def clip_stem(video_path: str | None) -> str | None:
    """File name without directory or extension, tolerating both separators:
    queue paths are written on Windows and read wherever the report runs."""
    if not video_path:
        return None
    name = os.path.basename(str(video_path).replace("\\", "/"))
    stem = os.path.splitext(name)[0]
    return stem or None


def find_words_file(stem: str, root: str = "work") -> Path | None:
    """The clip's `<stem>_words.json`, wherever its batch put it.

    Words files live under work/<video_stem>/subtitles/, and the clip stem alone
    does not say which video_stem that was - search all of them. When a clip was
    re-rendered the newest file wins."""
    matches = list(Path(root).glob(f"*/subtitles/{stem}_words.json"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def phrase_at(words: list[dict], second: float,
              window: float = PHRASE_WINDOW_SECONDS) -> str:
    """The words spoken in the `window` seconds up to and including `second`."""
    picked = [
        str(word.get("word", "")).strip()
        for word in words
        if word.get("start") is not None and word.get("end") is not None
        and word["end"] >= second - window and word["start"] <= second
    ]
    return " ".join(part for part in picked if part)


def annotate_drop_phrases(records: list[dict], root: str = "work") -> int:
    """Adds `record["drop"] = {"second", "phrase"}` to every record whose steepest
    drop can be placed on a word timeline. Returns how many were annotated.

    Fail-open per record: no drop, no clip stem, no words file, an unreadable
    one, or a phrase-less stretch (silence at the drop) just leaves the record
    as it was - the numbers in the report do not depend on this."""
    annotated = 0
    for record in records:
        drop = (record.get("analysis") or {}).get("biggest_drop")
        stem = record.get("clip_stem")
        if not drop or drop.get("at") is None or not stem:
            continue
        path = find_words_file(stem, root)
        if path is None:
            continue
        try:
            words = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not words:
            continue
        length = record.get("duration") or words[-1].get("end")
        if not length:
            continue
        second = drop["at"] * length
        phrase = phrase_at(words, second)
        record["drop"] = {"second": round(second, 1), "phrase": phrase}
        annotated += 1
    return annotated
