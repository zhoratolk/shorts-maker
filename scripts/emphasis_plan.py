"""Candidate emphasis_moves for one clip, ported from a sibling project
(shortmaker-business's worker/camera_plan.py) and adapted to this repo's
signals and PLAN.json schema.

Step 5 of SKILL.md currently hand-picks emphasis_moves by reading the
transcript/energy-spike cache directly - real but repetitive judgment: which
of the punch/energy signals already in hand are worth a pulse, spaced apart
enough not to read as a rendering fault. This module turns that judgment
into a mechanical pre-pass (same role scripts/jumpcuts.py plays for cut
points): it proposes candidates, Claude still decides whether the clip needs
any at all and can drop/adjust what's proposed - it never writes PLAN.json
directly.

Every input is in absolute recording seconds except punch_zoom_at, which
PLAN.json already stores clip-relative (post keep_segments remap, matching
render.py's own convention) - that asymmetry is intentional, not an
oversight, and is documented on plan_emphasis_moves below.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# How close two moves may land. audio-energy fires repeatedly on animated
# speech, and a clip that pulses on every spike reads as a rendering fault
# rather than an edit - this interval is the difference between the two.
MIN_INTERVAL_SECONDS = 3.0

DEFAULT_MAX_MOVES = 2
DEFAULT_KIND = "punch"
DEFAULT_TARGET = "action"

# Mirrors render.py's VALID_EMPHASIS_KINDS duration-by-kind table - kept as
# a separate constant rather than imported, so this module stays runnable
# standalone (same reasoning as VALID_TRANSITIONS's own duplication note).
_KIND_DURATIONS = {"zoom": 1.0, "punch": 0.6, "cut_in": 0.15}

# Which signal wins when two candidates land inside the same interval. The
# punch/climax is Claude's own explicit judgement about the moment (already
# vetted at candidate-refine time); energy is a heuristic over a waveform.
_REASON_PRIORITY = {"punch": 0, "energy": 1}


@dataclass(frozen=True)
class EmphasisCandidate:
    at: float  # seconds from clip start
    duration: float
    kind: str
    target: str
    reason: str  # "punch" | "energy" - dropped before writing to PLAN.json


def _energy_spikes_in_window(
    energy_spikes: list[dict], clip_start: float, clip_end: float
) -> list[float]:
    """Rebases audio_energy.py's absolute-second spikes onto clip-relative
    seconds, keeping only the ones whose start falls inside this clip's
    source window - same windowing scripts/render_batch.py's
    spikes_within does for thumbnail selection, duplicated here rather than
    imported so this module has no dependency on the batch renderer."""
    windowed = []
    for spike in energy_spikes:
        start = float(spike["start"])
        if clip_start <= start <= clip_end:
            windowed.append(start - clip_start)
    return windowed


def plan_emphasis_moves(
    clip_start: float,
    clip_end: float,
    punch_zoom_at: float | None = None,
    energy_spikes: list[dict] | None = None,
    min_interval: float = MIN_INTERVAL_SECONDS,
    max_moves: int = DEFAULT_MAX_MOVES,
    kind: str = DEFAULT_KIND,
    target: str = DEFAULT_TARGET,
) -> list[dict]:
    """An ordered, de-conflicted, priority-capped list of emphasis_moves
    candidates for one clip, ready to paste into a PLAN.json entry as-is (or
    trim further).

    clip_start/clip_end are absolute source seconds - the same window used
    to trim the clip. energy_spikes is audio_energy.py's cached list
    ({"start","end"} in absolute source seconds); punch_zoom_at, by
    contrast, is already clip-relative because that is how PLAN.json stores
    it (render.py's punch_zoom_at doc: "must already be expressed in
    seconds on the clip's final rendered timeline") - pass it through
    unchanged, do not subtract clip_start from it.

    An empty result is a valid and common answer: it means the clip renders
    exactly as it does without this feature, same as an omitted
    emphasis_moves field today.
    """
    duration = clip_end - clip_start
    if duration <= 0:
        return []
    move_duration = _KIND_DURATIONS.get(kind, 1.0)
    # No move may land in the final interval: there is no time left to read
    # it, and the punchline is usually the last thing that happens.
    latest = duration - min_interval

    candidates: list[EmphasisCandidate] = []
    if punch_zoom_at is not None and 0.0 <= punch_zoom_at <= duration:
        candidates.append(EmphasisCandidate(punch_zoom_at, move_duration, kind, target, "punch"))
    for at in _energy_spikes_in_window(energy_spikes or [], clip_start, clip_end):
        candidates.append(EmphasisCandidate(at, move_duration, kind, target, "energy"))

    candidates = [c for c in candidates if 0.0 <= c.at <= latest]

    # Selection order is priority first, then time, so a punch beats an
    # energy spike a second earlier; among equals the earlier one wins,
    # because the reaction that starts a beat is the one worth catching.
    kept: list[EmphasisCandidate] = []
    for candidate in sorted(candidates, key=lambda c: (_REASON_PRIORITY[c.reason], c.at)):
        if len(kept) >= max_moves:
            break
        if all(abs(candidate.at - chosen.at) >= min_interval for chosen in kept):
            kept.append(candidate)

    kept.sort(key=lambda c: c.at)
    return [
        {"at": round(c.at, 3), "duration": c.duration, "kind": c.kind, "target": c.target}
        for c in kept
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propose emphasis_moves candidates for one clip from its punch_zoom_at "
        "and the cached audio-energy spikes - a mechanical pre-pass for step 5, not a "
        "replacement for reviewing the result before it goes into PLAN.json.",
    )
    parser.add_argument("clip_start", type=float, help="Clip's start, absolute source seconds")
    parser.add_argument("clip_end", type=float, help="Clip's end, absolute source seconds")
    parser.add_argument(
        "--punch-zoom-at", type=float, default=None,
        help="This clip's punch_zoom_at, already clip-relative (as stored in PLAN.json)",
    )
    parser.add_argument(
        "--energy-spikes-json", default=None,
        help="Path to the cached <stem>_energy_spikes.json (absolute source seconds)",
    )
    parser.add_argument("--min-interval", type=float, default=MIN_INTERVAL_SECONDS)
    parser.add_argument("--max-moves", type=int, default=DEFAULT_MAX_MOVES)
    parser.add_argument("--kind", default=DEFAULT_KIND, choices=sorted(_KIND_DURATIONS))
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("action", "plate", "face"))
    args = parser.parse_args()

    energy_spikes = []
    if args.energy_spikes_json:
        cache = Path(args.energy_spikes_json)
        if cache.exists():
            energy_spikes = json.loads(cache.read_text(encoding="utf-8-sig"))

    moves = plan_emphasis_moves(
        args.clip_start, args.clip_end,
        punch_zoom_at=args.punch_zoom_at,
        energy_spikes=energy_spikes,
        min_interval=args.min_interval,
        max_moves=args.max_moves,
        kind=args.kind,
        target=args.target,
    )
    print(json.dumps(moves, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
