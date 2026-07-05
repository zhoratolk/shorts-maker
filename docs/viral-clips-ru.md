# What makes a gaming/stream short actually get watched (RU)

Guidance for SKILL.md step 3 ("Find candidates") and step 5's trim-point
decision. Synthesized from public research on short-form video virality —
not from downloading/analyzing specific third-party clips (no such source
material was available; see the notes below on what this is and isn't).
General audience-behavior and narrative-structure patterns, applied to
picking and trimming candidates from *this* streamer's own transcript —
not a copy of any one video's structure.

## The hook window (first ~1.5-3 seconds decide everything)

TikTok/Shorts algorithms make their first keep-or-scroll decision in
roughly 1.3-1.5 seconds of playback. A candidate whose actual hook (the
funny line, the reaction, the reveal) sits a few seconds into the window
with throat-clearing before it will lose most viewers before the hook even
plays — this is a **trim problem, not a content problem**: when scoring a
candidate in step 3, note whether the interesting part is at the very
front or buried; in step 5, trim `start` as close to the hook itself as
the sentence allows, even if that cuts a bit of setup a human editor might
have kept. A clip that opens mid-laugh/mid-reaction outperforms one that
opens with "so basically what happened was...".

## Length sweet spot

15-34 seconds gets the highest completion rates for a single self-contained
beat (one joke, one reaction, one exchange); up to 60 seconds is fine when
the moment genuinely needs that much room to land (a story with a real
setup, an escalating bit) — this lines up with `config.clip.min_seconds`/
`max_seconds` (30-60 by default). When a candidate's real content resolves
in 15-20s, don't pad it to fill the range — a tight clip beats a stretched
one. Completion rate (does the viewer watch to the end) matters more than
raw length, and a clip that ends right on the payoff completes better than
one that trails off after it.

## What actually gets picked as a candidate

- **Genuine, spontaneous reactions** (real rage, real shock, real laughter
  during play) outperform anything staged-sounding — this is most of why
  `config.analysis.hype_phrases` boosts a moment: the phrase itself is a
  marker that a real reaction is happening there, not filler.
- **One clean escalation or one clean setup→punchline**, not several
  unrelated beats stitched together — this is exactly what the
  `coherence` score (step 3, only when diarization is on) is measuring:
  a sustained single train of thought reads as one satisfying unit, a
  hopped-between-topics window reads as noise even if individual lines in
  it are funny.
- **A pattern interrupt** — something the viewer doesn't expect a beat
  into the clip (an unexpected turn, a reveal, a contradiction of what was
  just said/expected) holds attention better than a flat retelling.
- **Self-contained** — a viewer with zero stream context should be able to
  follow it. A moment that only makes sense if you already know who "Дима"
  is or what happened 20 minutes earlier is a weaker candidate than one
  that explains itself in-line, unless the missing context is trivial
  (a name, not a whole backstory).

## Anti-patterns — weaker candidates even when the line itself is funny

- Needs outside context the clip doesn't contain to land.
- Rambles across multiple unrelated topics before getting anywhere (low
  `coherence`).
- The actual hook is buried more than a few seconds into the window with
  nothing happening before it — flag this for a tighter trim in step 5
  rather than rejecting the candidate outright.
- A joke that requires reading a long setup at talking speed before the
  punchline — comedy that's mostly setup with a small payoff trims worse
  into short-form than a short setup with a big payoff.

## What this doc is not

This isn't a scrape or transcript analysis of specific viral videos (no
such source list existed for this project) — it's general short-form
video research applied to judgment calls on *this* streamer's own
material. Treat it as a lens alongside `hype_phrases` and `coherence`, not
a replacement for judging whether the moment is actually funny/interesting
in context — a technically well-structured clip about nothing is still a
bad candidate.

Sources: [TechTimes — Viral Gameplay in 2026](https://www.techtimes.com/articles/313453/20251218/viral-gameplay-2026-why-live-gaming-clips-dominate-youtube-shorts-tiktok-feeds.htm),
[Opus — TikTok Hooks That Go Viral 2026](https://www.opus.pro/blog/tiktok-hooks-that-go-viral-2026),
[Clypse — Best TikTok Gaming Clip Length 2026](https://clypse.ai/blog/best-tiktok-gaming-clip-length-2026),
[Praper Media — Viral YouTube Shorts 2026](https://prapermedia.com/blog/make-viral-youtube-shorts/),
[Medium — Setup-Punchline Combo](https://medium.com/screenwriting-storytelling/transcending-stand-up-comedy-by-mastering-the-setup-punchline-combo-f9bf6f4632df),
[Moonb — Storytelling Techniques That Trigger Virality](https://www.moonb.io/blog/techniques-that-trigger-virality).
