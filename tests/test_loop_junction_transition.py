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
