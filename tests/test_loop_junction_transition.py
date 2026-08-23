"""The rotate loop's INTERNAL junction is a scene change, not a seam.

Rotate mode produces [rotate_at, end) + [0, rotate_at). Two joins exist and
they are opposites:

  * the WRAP (last frame -> first frame on replay) is exact by construction —
    those frames were adjacent in the source. Nothing to hide.
  * the INTERNAL junction (punch end -> setup start) glues the clip's own end
    to its own beginning. Those are usually different scenes entirely, and a
    hard cut there is the one visible flaw of the whole shape.

`VALID_LOOP_TRANSITIONS` used to allow only cut/crossfade, reasoned about the
wrap ("a loop seam should be unsurprising, not eye-catching") but applied to
the junction, where the opposite is true — that is the same "snap into the
moment" job cold_open reaches for whip_pan to do.
"""
from __future__ import annotations

import pytest

from scripts.loop import VALID_LOOP_TRANSITIONS, build_punch_rotate_command
from scripts.render_common import RenderError


def rotate(transition, duration=0.35, rotate_at=12.0, base_duration=20.0):
    return build_punch_rotate_command(
        "in.mp4", "out.mp4", rotate_at, base_duration,
        transition=transition, transition_duration=duration,
    )


def graph(command):
    return command[command.index("-filter_complex") + 1]


def test_the_punchy_transitions_are_allowed_on_the_junction():
    assert {"cut", "crossfade", "whip_pan", "mask_wipe", "glitch", "match_cut"} <= VALID_LOOP_TRANSITIONS


def test_whip_pan_junction_builds_an_xfade_node():
    assert "xfade=transition=hblur" in graph(rotate("whip_pan"))


def test_mask_wipe_junction_builds_an_xfade_node():
    assert "xfade=transition=wipeleft" in graph(rotate("mask_wipe"))


def test_glitch_junction_layers_the_channel_split_over_a_pixelize_xfade():
    filtergraph = graph(rotate("glitch"))
    assert "xfade=transition=pixelize" in filtergraph
    assert "rgbashift" in filtergraph


def test_match_cut_joins_without_an_xfade_node_like_a_plain_cut():
    # match_cut means the two frames already line up - blending them would
    # smear a join that is invisible as-is.
    assert "xfade" not in graph(rotate("match_cut"))
    assert "xfade" not in graph(rotate("cut"))


def test_an_unknown_transition_is_still_refused():
    with pytest.raises(RenderError, match="loop transition must be one of"):
        rotate("teleport")


def test_a_zero_duration_transition_degrades_to_a_plain_join():
    assert "xfade" not in graph(rotate("whip_pan", duration=0.0))


def test_the_transition_is_clamped_to_the_punch_half_it_has_to_fit_inside():
    # punch half is [rotate_at, base_duration) = 2s here; a 5s blend cannot
    # overrun it, or the setup would start before the punch has played.
    filtergraph = graph(rotate("whip_pan", duration=5.0, rotate_at=18.0, base_duration=20.0))
    assert "duration=2.0" in filtergraph or "duration=2" in filtergraph


# --- a jump cut is a phrase boundary too (2026-08-23) ----------------------

import json

from scripts.jumpcuts import splice_points
from scripts.loop import last_phrase_start, phrase_starts


def _w(*pairs):
    return [{"word": f"w{i}", "start": a, "end": b} for i, (a, b) in enumerate(pairs)]


def test_splice_points_are_the_cuts_on_the_rendered_timeline():
    # 10s kept, 90s of source skipped, 5s kept -> one boundary, at 10s out
    assert splice_points([(0.0, 10.0), (100.0, 105.0)]) == [10.0]
    assert splice_points([(0.0, 4.0), (9.0, 12.0), (20.0, 21.0)]) == [4.0, 7.0]
    assert splice_points([(0.0, 10.0)]) == []
    assert splice_points([]) == []


def test_a_splice_starts_a_new_phrase_even_when_the_words_nearly_touch():
    # 0.2s apart: nowhere near the 0.6s pause threshold, but a 10s pause was
    # cut out right between them, so they are not one phrase.
    words = _w((0.0, 0.4), (0.5, 0.9), (1.1, 1.5))

    assert phrase_starts(words) == [0.0]
    assert phrase_starts(words, splice_points=[1.0]) == [0.0, 1.1]
    assert last_phrase_start(words, splice_points=[1.0]) == 1.1


def test_a_splice_a_hair_off_a_word_boundary_still_counts():
    words = _w((0.0, 0.4), (0.52, 0.9))

    # rounding can put the cut just inside either word
    assert phrase_starts(words, splice_points=[0.38]) == [0.0, 0.52]
    assert phrase_starts(words, splice_points=[0.55]) == [0.0, 0.52]


def test_phrase_starts_still_splits_on_a_plain_pause_with_no_cuts():
    words = _w((0.0, 0.4), (5.0, 5.4), (5.5, 5.9))

    assert phrase_starts(words) == [0.0, 5.0]


def _entry(tmp_path, words, keep_segments=None):
    subtitles = tmp_path / "clip.srt"
    subtitles.write_text("", encoding="utf-8")
    (tmp_path / "clip_words.json").write_text(json.dumps(words), encoding="utf-8")
    entry = {"subtitles_path": str(subtitles)}
    if keep_segments:
        entry["keep_segments"] = keep_segments
    return entry


def test_derive_falls_back_past_a_trailing_line_too_short_to_lead_with(tmp_path):
    from scripts.render import derive_loop_rotate_at

    # payoff at 16.0, then a stray "Ну." at 20.2 - the last phrase, but it
    # leaves 0.7s of punch against the 1.5s floor. Trying only that one used
    # to fail the whole rotation.
    words = _w((2.0, 2.5), (8.0, 8.5), (16.0, 16.4), (16.5, 17.0), (20.2, 20.5))

    assert derive_loop_rotate_at(_entry(tmp_path, words), 20.9) == 16.0


def test_derive_reads_the_clips_own_cuts_when_it_has_them(tmp_path):
    from scripts.render import derive_loop_rotate_at

    # words run continuously by their timestamps; only keep_segments knows a
    # 90-second pause was removed at the 12s mark.
    words = _w((1.0, 1.4), (6.0, 6.4), (11.6, 12.0), (12.1, 12.5), (12.6, 13.0))
    keep = [[0.0, 12.0], [102.0, 116.0]]

    assert derive_loop_rotate_at(_entry(tmp_path, words, keep), 26.0) == 12.1


def test_derive_still_returns_none_when_no_candidate_fits(tmp_path):
    from scripts.render import derive_loop_rotate_at

    # every phrase start sits inside the 4s setup floor
    words = _w((0.2, 0.6), (1.5, 1.9), (3.0, 3.4))

    assert derive_loop_rotate_at(_entry(tmp_path, words), 20.0) is None
