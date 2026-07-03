import json

import pytest

from scripts.render import (
    RenderError,
    ass_color,
    build_ass_content,
    build_ffmpeg_command,
    build_subtitle_force_style,
    clamp_clip_bounds,
    compute_crop_filter,
    probe_video,
    render_clip,
)


def test_clamp_clip_bounds_passthrough_when_within_range():
    assert clamp_clip_bounds(10.0, 40.0, video_duration=100.0) == (10.0, 40.0)


def test_clamp_clip_bounds_clamps_end_to_duration():
    assert clamp_clip_bounds(90.0, 120.0, video_duration=100.0) == (90.0, 100.0)


def test_clamp_clip_bounds_clamps_negative_start_to_zero():
    assert clamp_clip_bounds(-5.0, 10.0, video_duration=100.0) == (0.0, 10.0)


def test_clamp_clip_bounds_raises_when_start_after_clamped_end():
    with pytest.raises(RenderError, match="clip bounds invalid"):
        clamp_clip_bounds(150.0, 200.0, video_duration=100.0)


def test_clamp_clip_bounds_raises_on_non_positive_duration():
    with pytest.raises(RenderError, match="video_duration"):
        clamp_clip_bounds(0.0, 10.0, video_duration=0.0)


def test_compute_crop_filter_zoom():
    result = compute_crop_filter("zoom", src_width=1920, src_height=1080)
    assert result == "crop=608:1080:656:0,scale=1080:1920"


def test_compute_crop_filter_pad():
    result = compute_crop_filter("pad", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:656:black"


def test_compute_crop_filter_original_16_9():
    result = compute_crop_filter("original-16:9", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:656:black"


def test_compute_crop_filter_rejects_unresolved_auto():
    with pytest.raises(RenderError, match="resolved value"):
        compute_crop_filter("auto", src_width=1920, src_height=1080)


def test_build_ffmpeg_command_without_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0, crop_filter="crop=608:1080:656:0,scale=1080:1920"
    )

    assert command == [
        "ffmpeg", "-y",
        "-ss", "10.0",
        "-i", "in.mp4",
        "-t", "30.0",
        "-vf", "crop=608:1080:656:0,scale=1080:1920",
        "-c:v", "libx264",
        "-c:a", "aac",
        "out.mp4",
    ]


def test_build_ffmpeg_command_with_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="scale=1080:608,pad=1080:1920:0:394:black",
        subtitles_path="work/x/subs.srt",
    )

    assert command[9] == "scale=1080:608,pad=1080:1920:0:394:black,subtitles='work/x/subs.srt'"


def test_ass_color_named():
    assert ass_color("white") == "&H00FFFFFF"
    assert ass_color("black") == "&H00000000"


def test_ass_color_hex():
    assert ass_color("#FF8800") == "&H000088FF"


def test_build_subtitle_force_style_bottom_position():
    style = build_subtitle_force_style(
        font="Arial Black", size=72, color="white", outline_color="black", position="bottom"
    )

    assert style == (
        "FontName=Arial Black,FontSize=72,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        "Alignment=2,MarginV=380"
    )


def test_build_subtitle_force_style_top_and_center_positions():
    assert "Alignment=8" in build_subtitle_force_style("Arial", 48, "white", "black", "top")
    assert "Alignment=5" in build_subtitle_force_style("Arial", 48, "white", "black", "center")


def test_build_ffmpeg_command_with_subtitle_style():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="scale=1080:608,pad=1080:1920:0:394:black",
        subtitles_path="work/x/subs.srt",
        subtitle_style={"font": "Arial Black", "size": 72, "color": "white", "outline_color": "black", "position": "bottom"},
    )

    assert command[9] == (
        "scale=1080:608,pad=1080:1920:0:394:black,subtitles='work/x/subs.srt':"
        "force_style='FontName=Arial Black,FontSize=72,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        "Alignment=2,MarginV=380'"
    )


def test_build_ffmpeg_command_with_fade_out():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
    )

    assert command[9] == "crop=608:1080:656:0,scale=1080:1920,fade=t=out:st=29.5:d=0.5"
    assert command[10] == "-af"
    assert command[11] == "afade=t=out:st=29.5:d=0.5"
    assert command[-1] == "out.mp4"


def test_build_ffmpeg_command_fade_out_clamped_to_half_clip_duration():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=10.6,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
    )

    assert "fade=t=out:st=0.3:d=0.3" in command[9]


def test_build_ffmpeg_command_fade_starts_after_last_word_when_tail_available():
    # 60s of source footage remain past the clip's end -> fade happens in
    # extra appended footage instead of overlapping the last word.
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
        video_duration=100.0,
    )

    assert command[command.index("-t") + 1] == "30.5"
    assert "fade=t=out:st=30.0:d=0.5" in command[9]
    assert "afade=t=out:st=30.0:d=0.5" in command


def test_build_ffmpeg_command_fade_extend_clamped_to_available_tail():
    # only 0.2s of source footage remains past the clip's end
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
        video_duration=40.2,
    )

    assert command[command.index("-t") + 1] == "30.2"
    assert "fade=t=out:st=30.0:d=0.2" in command[9]


def test_build_ffmpeg_command_fade_falls_back_to_overlap_when_no_tail():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
        video_duration=40.0,
    )

    assert command[command.index("-t") + 1] == "30.0"
    assert "fade=t=out:st=29.5:d=0.5" in command[9]


def test_build_ffmpeg_command_without_fade_has_no_audio_filter():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    assert "-af" not in command


def test_probe_video_parses_ffprobe_json():
    fake_stdout = json.dumps(
        {
            "format": {"duration": "125.5"},
            "streams": [{"width": 1920, "height": 1080, "codec_type": "video"}],
        }
    )

    class FakeResult:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    def fake_runner(command, capture_output, text):
        return FakeResult()

    info = probe_video("in.mp4", runner=fake_runner)

    assert info == {"duration": 125.5, "width": 1920, "height": 1080}


def test_render_clip_builds_and_runs_command():
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        captured["command"] = command
        return FakeResult()

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom"}

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=fake_runner,
    )

    assert command == captured["command"]
    assert command[-1] == "out.mp4"
    assert "crop=608:1080:656:0,scale=1080:1920" in command


def test_render_clip_threads_fade_seconds_into_command():
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        captured["command"] = command
        return FakeResult()

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom"}

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        fade_seconds=0.5,
        runner=fake_runner,
    )

    assert command == captured["command"]
    assert "fade=t=out:st=30.0:d=0.5" in command[9]


def test_build_ass_content_sets_play_res_to_canvas_size():
    cues = [{"start": 0.26, "end": 2.18, "text": "hello world"}]

    ass = build_ass_content(cues, "Arial Black", 72, "white", "black", "bottom", 1080, 1920)

    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Alignment=2" not in ass  # baked into the Style line, not a force_style override
    assert "Style: Default,Arial Black,72,&H00FFFFFF,&H000000FF,&H00000000," in ass
    assert "Dialogue: 0,0:00:00.26,0:00:02.18,Default,,0,0,0,,hello world" in ass


def test_build_ass_content_escapes_newlines_as_hard_breaks():
    cues = [{"start": 0.0, "end": 1.0, "text": "line one\nline two"}]

    ass = build_ass_content(cues, "Arial", 48, "white", "black", "top", 1080, 1920)

    assert "line one\\Nline two" in ass


def test_render_clip_bakes_subtitles_into_ass_with_canvas_play_res(tmp_path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:00,260 --> 00:00:02,180\nhello world\n\n", encoding="utf-8"
    )

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        captured["command"] = command
        return FakeResult()

    plan_entry = {
        "start": 10.0, "end": 40.0, "crop_style": "zoom",
        "subtitles_path": str(srt_path),
    }
    subtitle_style = {
        "font": "Arial Black", "size": 72, "color": "white",
        "outline_color": "black", "position": "bottom",
    }

    render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        subtitle_style=subtitle_style,
        runner=fake_runner,
    )

    ass_path = srt_path.with_suffix(".ass")
    assert ass_path.exists()
    ass_content = ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in ass_content
    assert "PlayResY: 1920" in ass_content

    command = captured["command"]
    assert any("subtitles=" in part and ".ass" in part for part in command)
    assert not any("force_style" in part for part in command)


def test_render_clip_raises_on_ffmpeg_failure():
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def fake_runner(command, capture_output, text):
        return FakeResult()

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom"}

    with pytest.raises(RenderError, match="boom"):
        render_clip(
            "in.mp4", "out.mp4", plan_entry,
            video_duration=100.0, src_width=1920, src_height=1080,
            runner=fake_runner,
        )
