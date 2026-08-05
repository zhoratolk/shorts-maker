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
    build_render_args,
    is_loop_entry,
    run_pass,
    split_plan,
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
    config = make_config(hook_banner={"enabled": True, "mode": "hook"})
    assert _thumbnail_text(entry, config) == expected


def test_persistent_banner_is_not_repeated_as_the_poster_caption():
    """The banner is burned into every frame in persistent mode, so borrowing
    it would print the same sentence twice on one image."""
    config = make_config(hook_banner={"enabled": True, "mode": "persistent"})

    assert _thumbnail_text({"banner_text": "Мешаю своим же"}, config) == ""
    # an explicit caption still wins - it is deliberate, not a fallback
    assert _thumbnail_text(
        {"banner_text": "Мешаю своим же", "thumbnail_text": "свои же"}, config
    ) == "свои же"


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
