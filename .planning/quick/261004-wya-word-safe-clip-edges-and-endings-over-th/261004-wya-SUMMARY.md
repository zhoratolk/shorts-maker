---
quick_id: 261004-wya
status: complete
commit: 2a6c8ff
date: 2026-10-04
---

# Summary: word-safe clip edges, and endings over the length cap

**Code.** `scripts/jumpcuts.py` gained two functions:
- `load_words`: reads a word list, a segment list, or the cached transcript;
- `snap_edges_to_words`: moves a clip edge out of a word, by at most 1 s, never into the next word.

`compute_keep_segments(words=...)` applies the snap. The `keep-segments` CLI takes the
transcript as `--words-json` and prints any edges it moved. Tests: 8 new in
`tests/test_jumpcuts.py`. The full suite (1468, without integration) is green.

**Skill.** `SKILL.md` now:
- passes the cached transcript to `keep-segments` and takes the entry's `start`/`end` from it;
- trims on word timestamps, not segment ones;
- lets the ending run past `max_seconds` up to 35 s rather than cutting before the
  sentence finishes.

**Verified on the server.** `jumpcuts.py` was deployed there; the previous copy is kept
as `jumpcuts.py.bak-20261004`.
- The 2026-09-05 clip: end 7098.0 -> 7098.49, «плавал.» kept.
- All 68 planned clips replayed:

| | old | new |
|---|---|---|
| words lost in algorithmic cuts | 41 | 6 |
| clips with an edge inside a word | 14 | 5 |
| clips lengthened | | 36, at most +2.0 s |

The remaining 5 are whisper words stretched past the 1 s cap.

**Not done.**
- `config.py`: the server copy differs from both local branches.
- Hand-made multi-word cuts: those are deliberate tangent removal.
