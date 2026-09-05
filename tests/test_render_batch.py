"""Tests for the config-driven batch render wrapper.

The point of scripts/render_batch.py is that a render feature can only be off
when config.yaml says it's off - so these tests assert on the presence and
absence of specific flags, which is exactly what the 2026-08-06 silent-no-op
incident turned on.
"""

from __future__ import annotations

import json

import pytest

from scripts.config import Config
from scripts.render_batch import (
    autoframe_entries,
    build_render_args,
    entry_segments,
    entry_source_window,
    is_loop_entry,
    load_energy_spikes,
    run_pass,
    split_plan,
    spikes_within,
    write_pass_plan,
    _thumbnail_text,
)


def make_config(**overrides) -> Config:
    config = Config(input_dir="in", output_dir="out")
    for section, values in overrides.items():
        for key, value in values.items():
            setattr(getattr(config, section), key, value)
    return config


def flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_split_plan_keeps_order_within_each_group():
    entries = [
        {"output_filename": "a.mp4"},
        {"output_filename": "b.mp4", "loop": True},
        {"output_filename": "c.mp4"},
        {"output_filename": "d.mp4", "loop": True},
    ]
    regular, loops = split_plan(entries)
    assert [entry["output_filename"] for entry in regular] == ["a.mp4", "c.mp4"]
    assert [entry["output_filename"] for entry in loops] == ["b.mp4", "d.mp4"]


@pytest.mark.parametrize(
    "entry,expected",
    [({}, False), ({"loop": False}, False), ({"loop": True}, True)],
)
def test_is_loop_entry(entry, expected):
    assert is_loop_entry(entry) is expected


def test_positionals_come_first():
    args = build_render_args(make_config(), "video.mkv", "PLAN.json", "outdir")
    assert args[:3] == ["video.mkv", "PLAN.json", "outdir"]


def test_boolean_flags_emit_an_explicit_form_either_way():
    on = build_render_args(
        make_config(subtitles={"censor_profanity": True}, audio={"denoise": True}),
        "v", "p", "o",
    )
    assert "--censor-subtitles" in on and "--no-censor-subtitles" not in on
    assert "--denoise" in on

    off = build_render_args(
        make_config(subtitles={"censor_profanity": False}, audio={"denoise": False}),
        "v", "p", "o",
    )
    assert "--no-censor-subtitles" in off and "--censor-subtitles" not in off
    assert "--no-denoise" in off


def test_profanity_sound_mask_carries_its_sound_path():
    config = make_config(
        profanity={"enabled": True, "mask_mode": "sound", "mask_sound_path": "assets/beep.wav"}
    )
    args = build_render_args(config, "v", "p", "o")
    assert flag_value(args, "--profanity-mask-mode") == "sound"
    assert flag_value(args, "--profanity-mask-sound-path") == "assets/beep.wav"


def test_disabled_sections_emit_no_flags():
    args = build_render_args(make_config(), "v", "p", "o")
    for flag in (
        "--emphasis-enabled",
        "--social-enabled",
        "--cold-open-enabled",
        "--outro-enabled",
        "--loop-enabled",
        "--profanity-mask-mode",
        "--banner-mode",
    ):
        assert flag not in args


def test_social_capsules_only_for_configured_platforms():
    config = make_config(
        social_overlay={
            "enabled": True,
            "platforms": ["twitch", "telegram"],
            "labels": {"twitch": "twitch.tv/ZhorikP", "telegram": "t.me/zhorekp", "kick": "kick/x"},
            "icon_paths": {"twitch": "assets/twitch.png"},
        }
    )
    args = build_render_args(config, "v", "p", "o")
    assert flag_value(args, "--social-twitch-label") == "twitch.tv/ZhorikP"
    assert flag_value(args, "--social-twitch-icon") == "assets/twitch.png"
    assert flag_value(args, "--social-telegram-label") == "t.me/zhorekp"
    assert "--social-telegram-icon" not in args  # no glyph configured
    assert "--social-kick-label" not in args     # platform not enabled


def test_loop_pass_drops_outro_and_cold_open():
    config = make_config(
        loop={"enabled": True, "transition": "crossfade", "transition_duration": 0.4},
        cold_open={"enabled": True},
        outro_card={"enabled": True, "nick": "ZhorikP"},
    )
    args = build_render_args(config, "v", "p", "o", loop_pass=True)
    assert "--loop-enabled" in args
    assert flag_value(args, "--loop-transition") == "crossfade"
    assert "--outro-enabled" not in args
    assert "--cold-open-enabled" not in args


def test_regular_pass_keeps_outro_and_cold_open_but_never_loops():
    config = make_config(
        loop={"enabled": True},
        cold_open={"enabled": True},
        outro_card={"enabled": True, "nick": "ZhorikP", "tagline": "Заходите на стримы"},
    )
    args = build_render_args(config, "v", "p", "o", loop_pass=False)
    assert "--loop-enabled" not in args
    assert "--cold-open-enabled" in args
    assert flag_value(args, "--outro-nick") == "ZhorikP"
    assert flag_value(args, "--outro-tagline") == "Заходите на стримы"


def test_empty_outro_text_fields_are_omitted_not_passed_blank():
    config = make_config(outro_card={"enabled": True, "nick": "ZhorikP"})
    args = build_render_args(config, "v", "p", "o")
    assert "--outro-nick" in args
    assert "--outro-tagline" not in args
    assert "--outro-icon" not in args


def test_encoder_settings_come_from_config():
    args = build_render_args(
        make_config(video={"codec": "h264_nvenc", "preset": "", "crf": None}), "v", "p", "o"
    )
    assert flag_value(args, "--video-codec") == "h264_nvenc"
    assert "--preset" not in args and "--crf" not in args

    args = build_render_args(make_config(video={"preset": "veryfast", "crf": 21}), "v", "p", "o")
    assert flag_value(args, "--preset") == "veryfast"
    assert flag_value(args, "--crf") == "21"


def test_hwaccel_none_is_omitted_default():
    args = build_render_args(make_config(), "v", "p", "o")
    assert "--hwaccel" not in args


def test_hwaccel_cuda_is_passed_through():
    args = build_render_args(make_config(video={"hwaccel": "cuda"}), "v", "p", "o")
    assert flag_value(args, "--hwaccel") == "cuda"


def test_parallel_clips_one_is_omitted_default():
    args = build_render_args(make_config(), "v", "p", "o")
    assert "--render-parallel-clips" not in args


def test_parallel_clips_above_one_is_passed_through():
    args = build_render_args(make_config(video={"parallel_clips": 4}), "v", "p", "o")
    assert flag_value(args, "--render-parallel-clips") == "4"


def test_write_pass_plan_writes_bom_free_utf8(tmp_path):
    plan = tmp_path / "PLAN.json"
    plan.write_text("[]", encoding="utf-8")
    entries = [{"output_filename": "клип.mp4", "loop": True}]

    target = write_pass_plan(entries, str(plan), "loop")

    assert target.endswith("PLAN_loop.json")
    raw = (tmp_path / "PLAN_loop.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8")) == entries


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"thumbnail_text": "фиаско", "banner_text": "ignored"}, "фиаско"),
        ({"banner_text": "500 пробития"}, "500 пробития"),
        ({}, ""),
    ],
)
def test_thumbnail_text_falls_back_through_the_plan_entry(entry, expected):
    assert _thumbnail_text(entry) == expected


def test_entry_source_window_spans_the_whole_moment_across_jump_cuts():
    assert entry_source_window({"start": 10.0, "end": 40.0}) == (10.0, 40.0)
    assert entry_source_window(
        {"start": 10.0, "end": 40.0, "keep_segments": [[12.0, 20.0], [25.0, 38.0]]}
    ) == (12.0, 38.0)


def test_load_energy_spikes_weighs_by_how_long_a_spike_lasts(tmp_path):
    cache = tmp_path / "transcripts"
    cache.mkdir()
    (cache / "rec_energy_spikes.json").write_text(
        json.dumps([
            {"start": 10.0, "end": 10.4, "reason": "audio energy spike"},
            {"start": 30.0, "end": 32.0, "reason": "audio energy spike"},
        ]),
        encoding="utf-8",
    )
    config = make_config()
    config.output_dir = str(tmp_path)

    spikes = load_energy_spikes(config, "F:/rec.mkv")

    assert spikes == [{"at": 10.2, "weight": 0.4}, {"at": 31.0, "weight": 2.0}]


def test_load_energy_spikes_fails_open_when_the_pass_never_ran(tmp_path):
    config = make_config()
    config.output_dir = str(tmp_path)

    assert load_energy_spikes(config, "F:/never_analysed.mkv") == []


def test_spikes_within_rebases_onto_the_clips_own_timeline():
    spikes = [
        {"at": 5.0, "weight": 1.0},     # before the clip
        {"at": 105.0, "weight": 2.0},
        {"at": 130.0, "weight": 3.0},
        {"at": 500.0, "weight": 4.0},   # after the clip
    ]

    inside = spikes_within(spikes, 100.0, 140.0)

    assert inside == [{"at": 5.0, "weight": 2.0}, {"at": 30.0, "weight": 3.0}]


def test_run_pass_invokes_render_as_a_module():
    captured = {}

    class Result:
        returncode = 0

    def runner(command):
        captured["command"] = command
        return Result()

    code = run_pass(make_config(), "v.mkv", "p.json", "out", loop_pass=False, runner=runner)

    assert code == 0
    assert captured["command"][1:3] == ["-m", "scripts.render"]
    assert captured["command"][3:6] == ["v.mkv", "p.json", "out"]


def test_dry_run_does_not_execute(capsys):
    def runner(command):  # pragma: no cover - must never be called
        raise AssertionError("dry run must not execute the render")

    assert run_pass(
        make_config(), "v.mkv", "p.json", "out", loop_pass=True, dry_run=True, runner=runner
    ) == 0
    assert "scripts.render" in capsys.readouterr().out


def test_dead_zone_gap_measures_only_the_8_to_16s_window():
    from scripts.render_batch import dead_zone_gap

    words = [
        {"word": "a", "start": 0.0, "end": 1.0},   # silence 1-9s, but only 8-9 counts
        {"word": "b", "start": 9.0, "end": 9.5},
        {"word": "c", "start": 13.0, "end": 14.0},  # 3.5s gap inside the zone
        {"word": "d", "start": 14.1, "end": 20.0},
    ]
    assert dead_zone_gap(words) == 3.5


def test_dead_zone_gap_counts_a_clip_that_ends_before_the_zone():
    from scripts.render_batch import dead_zone_gap

    words = [{"word": "a", "start": 1.0, "end": 6.0}]
    # nothing said from 6s on -> the whole 8-16s zone is silent
    assert dead_zone_gap(words) == 8.0


def test_dead_zone_gap_is_zero_for_continuous_speech():
    from scripts.render_batch import dead_zone_gap

    words = [{"word": str(i), "start": float(i), "end": float(i) + 0.9} for i in range(20)]
    assert dead_zone_gap(words) == 0.1


def test_dead_zone_warnings_names_the_offending_clip(tmp_path):
    import json as _json

    from scripts.render_batch import dead_zone_warnings

    (tmp_path / "clip_words.json").write_text(
        _json.dumps([{"word": "a", "start": 1.0, "end": 6.0}]), encoding="utf-8"
    )
    entries = [{
        "output_filename": "clip.mp4",
        "subtitles_path": str(tmp_path / "clip.srt"),
    }]
    warnings = dead_zone_warnings(entries)
    assert len(warnings) == 1
    assert "clip.mp4" in warnings[0]


def test_dead_zone_warnings_stays_quiet_without_a_words_file(tmp_path):
    from scripts.render_batch import dead_zone_warnings

    entries = [{"output_filename": "clip.mp4", "subtitles_path": str(tmp_path / "clip.srt")}]
    assert dead_zone_warnings(entries) == []


def _framing_stub(result):
    def fake_plan_focus(video_path, segments, src_width, src_height, **kwargs):
        fake_plan_focus.calls.append((video_path, segments, kwargs["crop_width"]))
        return result
    fake_plan_focus.calls = []
    return fake_plan_focus


def test_autoframe_fills_a_zoom_entry_that_left_the_framing_out(monkeypatch):
    stub = _framing_stub({"focus_x": 28.0, "static": False})
    monkeypatch.setattr("scripts.render_batch.plan_focus", stub)
    entries = [{"start": 10.0, "end": 40.0, "crop_style": "zoom"}]

    changed, warnings = autoframe_entries(
        "in.mp4", entries, 1920, 1080, target_width=1080, target_height=1920
    )

    assert changed is True
    assert warnings == []
    assert entries[0]["crop_focus_x"] == 28.0
    # 1080 * 1080/1920 = 607.5 -> 608, the same window compute_crop_filter uses
    assert stub.calls[0][2] == 608


def test_autoframe_uses_the_kept_segments_when_the_clip_is_jump_cut(monkeypatch):
    stub = _framing_stub({"focus_keyframes": [[1.0, 20.0], [9.0, 70.0]], "static": False})
    monkeypatch.setattr("scripts.render_batch.plan_focus", stub)
    entries = [{
        "start": 10.0, "end": 40.0, "crop_style": "zoom",
        "keep_segments": [[10.0, 20.0], [30.0, 40.0]],
    }]

    autoframe_entries("in.mp4", entries, 1920, 1080, target_width=1080, target_height=1920)

    assert stub.calls[0][1] == [(10.0, 20.0), (30.0, 40.0)]
    assert entries[0]["crop_focus_keyframes"] == [[1.0, 20.0], [9.0, 70.0]]
    assert "crop_focus_x" not in entries[0]


def test_autoframe_never_overrides_framing_the_plan_already_states(monkeypatch):
    stub = _framing_stub({"focus_x": 90.0, "static": False})
    monkeypatch.setattr("scripts.render_batch.plan_focus", stub)
    entries = [
        {"start": 0.0, "end": 5.0, "crop_style": "zoom", "crop_focus_x": 12},
        {"start": 0.0, "end": 5.0, "crop_style": "zoom", "crop_focus_keyframes": [[0.0, 5.0]]},
    ]

    changed, _ = autoframe_entries(
        "in.mp4", entries, 1920, 1080, target_width=1080, target_height=1920
    )

    assert changed is False
    assert stub.calls == []
    assert entries[0]["crop_focus_x"] == 12


def test_autoframe_skips_styles_that_do_not_crop_horizontally(monkeypatch):
    stub = _framing_stub({"focus_x": 90.0, "static": False})
    monkeypatch.setattr("scripts.render_batch.plan_focus", stub)
    entries = [
        {"start": 0.0, "end": 5.0, "crop_style": "pad"},
        {"start": 0.0, "end": 5.0, "crop_style": "original-16:9"},
    ]

    changed, _ = autoframe_entries(
        "in.mp4", entries, 1920, 1080, target_width=1080, target_height=1920
    )

    assert changed is False
    assert stub.calls == []


def test_autoframe_warns_about_a_clip_whose_picture_never_moves(monkeypatch):
    monkeypatch.setattr(
        "scripts.render_batch.plan_focus", _framing_stub({"focus_x": 30.0, "static": True})
    )
    entries = [{
        "start": 0.0, "end": 5.0, "crop_style": "zoom",
        "output_filename": "scoreboard.mp4",
    }]

    _, warnings = autoframe_entries(
        "in.mp4", entries, 1920, 1080, target_width=1080, target_height=1920
    )

    assert len(warnings) == 1
    assert "scoreboard.mp4" in warnings[0]
    assert "barely moves" in warnings[0]


def test_autoframe_leaves_the_entry_alone_when_nothing_could_be_measured(monkeypatch):
    monkeypatch.setattr("scripts.render_batch.plan_focus", _framing_stub(None))
    entries = [{"start": 0.0, "end": 5.0, "crop_style": "zoom"}]

    changed, warnings = autoframe_entries(
        "in.mp4", entries, 1920, 1080, target_width=1080, target_height=1920
    )

    assert changed is False
    assert warnings == []
    assert entries[0] == {"start": 0.0, "end": 5.0, "crop_style": "zoom"}


def test_entry_segments_declines_a_compilation_entry():
    assert entry_segments({"segments": [{"start": 1.0, "end": 2.0}]}) is None
    assert entry_segments({"start": 1.0, "end": 2.0}) == [(1.0, 2.0)]


# --- autoloop: measure the junction instead of guessing at it --------------


def _loop_entry(**overrides):
    entry = {"start": 100.0, "end": 130.0, "loop": True, "crop_style": "zoom",
             "output_filename": "clip.mp4"}
    entry.update(overrides)
    return entry


def test_autoloop_leaves_an_entry_that_named_its_own_transition(monkeypatch):
    from scripts.render_batch import autoloop_entries

    def must_not_run(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("an explicit loop_transition must not be re-measured")

    monkeypatch.setattr("subprocess.run", must_not_run)
    entries = [_loop_entry(loop_transition="glitch")]

    assert autoloop_entries("in.mp4", entries) == (False, [])
    assert entries[0]["loop_transition"] == "glitch"


def test_autoloop_ignores_entries_that_are_not_loops(monkeypatch):
    from scripts.render_batch import autoloop_entries

    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    entries = [{"start": 1.0, "end": 20.0, "crop_style": "zoom"}]

    assert autoloop_entries("in.mp4", entries) == (False, [])
    assert "loop_transition" not in entries[0]


def _stub_measurement(monkeypatch, similarity, motion):
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    monkeypatch.setattr("scripts.transitions.analyze_similarity_at_boundary",
                        lambda a, b: similarity)
    monkeypatch.setattr("scripts.transitions.analyze_motion_at_boundary",
                        lambda a, b: motion)


def test_autoloop_keeps_a_cut_when_the_two_frames_already_match(monkeypatch):
    # Same shot either side: blending would smear a join nobody can see.
    from scripts.render_batch import autoloop_entries

    _stub_measurement(monkeypatch, similarity=0.97, motion=40.0)
    entries = [_loop_entry()]

    filled, warnings = autoloop_entries("in.mp4", entries)

    assert filled is True and warnings == []
    assert entries[0]["loop_transition"] == "match_cut"


def test_autoloop_covers_a_scene_jump_with_a_real_transition(monkeypatch):
    from scripts.render_batch import autoloop_entries

    _stub_measurement(monkeypatch, similarity=0.10, motion=60.0)
    entries = [_loop_entry()]

    autoloop_entries("in.mp4", entries)

    assert entries[0]["loop_transition"] not in ("cut", "match_cut")


def test_autoloop_falls_back_to_cut_when_nothing_could_be_measured(monkeypatch):
    from scripts.render_batch import autoloop_entries

    _stub_measurement(monkeypatch, similarity=None, motion=None)
    entries = [_loop_entry()]

    autoloop_entries("in.mp4", entries)

    assert entries[0]["loop_transition"] == "cut"


def test_autoloop_reports_a_failed_measurement_without_raising(monkeypatch):
    from scripts.render_batch import autoloop_entries

    def boom(*args, **kwargs):
        raise OSError("ffmpeg is not on PATH")

    monkeypatch.setattr("subprocess.run", boom)
    entries = [_loop_entry()]

    filled, warnings = autoloop_entries("in.mp4", entries)

    assert filled is False
    assert len(warnings) == 1 and "loop junction not measured" in warnings[0]
    assert "loop_transition" not in entries[0]


def test_classify_loop_junction_reads_visual_continuity_not_motion():
    from scripts.render_batch import classify_loop_junction

    # the numbers in the comment above the thresholds, as behaviour
    assert classify_loop_junction(0.997, 5.60) == "match_cut"   # same shot
    assert classify_loop_junction(1.000, 0.16) == "match_cut"   # two stills, identical
    assert classify_loop_junction(0.414, 5.75) == "whip_pan"    # unrelated scenes
    assert classify_loop_junction(0.318, 5.53) == "whip_pan"


def test_classify_loop_junction_wipes_rather_than_whips_a_frozen_picture():
    from scripts.render_batch import classify_loop_junction

    # a motion blur across two still screens reads as a rendering fault
    assert classify_loop_junction(0.30, 0.2) == "mask_wipe"


def test_classify_loop_junction_dissolves_a_related_but_not_identical_join():
    from scripts.render_batch import classify_loop_junction

    assert classify_loop_junction(0.75, 5.0) == "crossfade"


def test_classify_loop_junction_falls_back_to_cut_without_a_similarity_score():
    from scripts.render_batch import classify_loop_junction

    assert classify_loop_junction(None, 5.0) == "cut"


def test_dead_zone_stops_where_the_clip_does():
    """Клип короче 16 секунд — обычное дело после агрессивных jumpcut'ов.

    Зона считалась до фиксированных 16 с, так что предупреждение приходило про отрезок,
    которого в клипе нет. Поток ложных предупреждений приучает пролистывать и настоящие.
    """
    from scripts.render_batch import dead_zone_gap

    words = [{"start": 5.0, "end": 6.0, "word": "всё"}]

    assert dead_zone_gap(words) == 8.0
    assert dead_zone_gap(words, clip_length=12.0) == 4.0
    assert dead_zone_gap(words, clip_length=7.0) == 0.0


def test_a_clip_shorter_than_the_zone_has_no_dead_zone_at_all():
    from scripts.render_batch import dead_zone_gap

    words = [{"start": 1.0, "end": 2.0, "word": "раз"}]

    assert dead_zone_gap(words, clip_length=8.0) == 0.0


# --- two-key features: config switch on, plan field missing -----------------
# The silent-no-op class of bug the 2026-08-27..09-04 batches ran into: the
# flag reaches render.py, the per-entry gate finds nothing, and 40 clips ship
# without a cold open, a punch zoom or a loop while every log line looks fine.


def test_unused_feature_warnings_flags_a_batch_with_no_cold_open():
    from scripts.render_batch import unused_feature_warnings

    config = make_config(cold_open={"enabled": True})
    warnings = unused_feature_warnings(config, [{"output_filename": "clip.mp4"}])
    assert len(warnings) == 1
    assert "cold_open" in warnings[0]


def test_unused_feature_warnings_quiet_when_one_entry_has_the_field():
    from scripts.render_batch import unused_feature_warnings

    config = make_config(cold_open={"enabled": True})
    entries = [{"output_filename": "a.mp4"}, {"cold_open": {"at": 1.0, "duration": 2.0}}]
    assert unused_feature_warnings(config, entries) == []


def test_unused_feature_warnings_quiet_when_the_feature_is_off():
    from scripts.render_batch import unused_feature_warnings

    config = make_config(cold_open={"enabled": False}, loop={"enabled": False},
                         emphasis={"enabled": False})
    assert unused_feature_warnings(config, [{"output_filename": "clip.mp4"}]) == []


def test_unused_feature_warnings_covers_loop_and_emphasis():
    from scripts.render_batch import unused_feature_warnings

    config = make_config(cold_open={"enabled": False}, loop={"enabled": True},
                         emphasis={"enabled": True})
    warnings = unused_feature_warnings(config, [{"output_filename": "clip.mp4"}])
    assert len(warnings) == 2
    assert any("loop" in w for w in warnings)
    assert any("emphasis_moves" in w for w in warnings)


def test_unused_feature_warnings_punch_zoom_needs_a_zoom_clip():
    from scripts.render_batch import unused_feature_warnings

    config = make_config(cold_open={"enabled": False}, loop={"enabled": False},
                         emphasis={"enabled": False})
    padded = [{"output_filename": "clip.mp4", "crop_style": "pad"}]
    assert unused_feature_warnings(config, padded) == []

    zoomed = [{"output_filename": "clip.mp4", "crop_style": "zoom"}]
    warnings = unused_feature_warnings(config, zoomed)
    assert len(warnings) == 1
    assert "punch_zoom_at" in warnings[0]
