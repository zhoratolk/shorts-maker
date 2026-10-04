---
quick_id: 261004-wya
slug: word-safe-clip-edges-and-endings-over-th
date: 2026-10-04
mode: quick (inline, no subagents)
---

# Word-safe clip edges, and endings over the length cap

Audit of the 68 single clips in the server's `work/*/PLAN.json` against their own
word-level chunk transcripts (read-only):

| | before 2026-09-04 (cap 35) | from 2026-09-04 (cap 26) |
|---|---|---|
| clips | 28 | 40 |
| clip end falls inside a word | 4 | 11 |
| clip ends mid-phrase (speech carries on, no sentence end) | 2 | 9 |

- Worst case: 2026-09-05, the clip ends at 7098.0 while «плавал.» runs 7097.97-7098.39, so
  the last word is gone. The end was taken from a segment timestamp. A segment can end
  before its own last word does.
- 20 jump cuts swallowed exactly one word at their boundary («говно», «почему», «кого»,
  «ветеран»). `clamp_cuts_to_words` (7d66f46) exists to stop this, but `--words-json` is
  opt-in and SKILL.md never passes it, so it has never run in the real flow.

## Tasks

1. `scripts/jumpcuts.py`
   - `load_words`: a flat word list, a segment list, or the cached transcript dict.
   - `snap_edges_to_words`: a clip edge that falls inside a word moves out to that word's
     edge plus the guard, by at most 1 s and never into the neighbouring word.
   - `compute_keep_segments(words=...)` snaps the edges before computing the cuts.
   - The `keep-segments` CLI accepts the transcript and prints the final clip edges.
2. `tests/test_jumpcuts.py`: loader shapes, edge snapping, bounds, the
   keep-segments integration, the CLI on a transcript file.
3. `SKILL.md`
   - Pass the cached transcript to `keep-segments`, and take `start`/`end` from the
     keep file.
   - Trim on word timestamps, not segment ones.
   - The ending wins over `max_seconds`: trim the setup first, then run past the cap up
     to 35 s (the channel's retention cliff), and never cut before the sentence ends.

## Out of scope

- `config.py`: the server copy differs from both branches.
- Hand-made multi-word cuts: those are deliberate tangent removal.

## Verify

- Full pytest suite green.
- Replay the 2026-09-05 «плавал.» clip through the new `keep-segments` on the server.
