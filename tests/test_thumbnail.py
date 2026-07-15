import pytest

from scripts.thumbnail import (
    ThumbnailError,
    build_thumbnail_command,
    generate_thumbnail,
    pick_thumbnail_timestamp,
)


# --- pick_thumbnail_timestamp ---------------------------------------------

def test_pick_timestamp_no_spikes_is_midpoint():
    assert pick_thumbnail_timestamp(40.0) == 20.0


def test_pick_timestamp_zero_duration_raises():
    with pytest.raises(ThumbnailError, match="clip_duration"):
        pick_thumbnail_timestamp(0)


def test_pick_timestamp_picks_strongest_spike_in_band():
    # band for 100s clip = [15, 85]. Two in-band spikes; higher score wins.
    spikes = [{"at": 20.0, "score": 1.0}, {"at": 60.0, "score": 5.0}, {"at": 90.0, "score": 9.0}]
    assert pick_thumbnail_timestamp(100.0) is not None
    assert pick_thumbnail_timestamp(100.0, spikes) == 60.0  # 90 is out of band, ignored


def test_pick_timestamp_out_of_band_spike_clamped():
    # Only spike is past the safe band -> clamp to hi edge (85% of 100).
    assert pick_thumbnail_timestamp(100.0, [{"at": 95.0, "score": 3.0}]) == 85.0


def test_pick_timestamp_bare_floats_tiebreak_toward_centre():
    # Equal (zero) weight -> nearest the centre (50) wins: 45 beats 20.
    assert pick_thumbnail_timestamp(100.0, [20.0, 45.0]) == 45.0


# --- build_thumbnail_command ----------------------------------------------

def test_build_command_basic_shape():
    cmd = build_thumbnail_command("clip.mp4", 12.5, "BIG WIN", "out.png")
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "12.500"
    assert cmd[cmd.index("-i") + 1] == "clip.mp4"
    assert cmd[-1] == "out.png"
    assert "-frames:v" in cmd


def test_build_command_covers_and_crops_to_size():
    cmd = build_thumbnail_command("clip.mp4", 1.0, "", "out.png", width=1280, height=720)
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1280:720:force_original_aspect_ratio=increase" in vf
    assert "crop=1280:720" in vf


def test_build_command_empty_caption_has_no_drawtext():
    vf = build_thumbnail_command("clip.mp4", 1.0, "   ", "out.png")[
        build_thumbnail_command("clip.mp4", 1.0, "   ", "out.png").index("-vf") + 1
    ]
    assert "drawtext" not in vf


def test_build_command_caption_adds_drawtext_clause():
    cmd = build_thumbnail_command("clip.mp4", 1.0, "GG EZ", "out.png")
    vf = cmd[cmd.index("-vf") + 1]
    assert "drawtext=" in vf
    assert "GG EZ" in vf


def test_build_command_escapes_special_chars():
    cmd = build_thumbnail_command("clip.mp4", 1.0, "50%: it's over, boys", "out.png")
    vf = cmd[cmd.index("-vf") + 1]
    assert "\\:" in vf  # colon escaped
    assert "\\'" in vf  # apostrophe escaped


def test_build_command_rejects_bad_position():
    with pytest.raises(ThumbnailError, match="position"):
        build_thumbnail_command("clip.mp4", 1.0, "x", "out.png", position="sideways")


def test_build_command_rejects_negative_timestamp():
    with pytest.raises(ThumbnailError, match="timestamp"):
        build_thumbnail_command("clip.mp4", -1.0, "x", "out.png")


def test_build_command_rejects_bad_opacity():
    with pytest.raises(ThumbnailError, match="box_opacity"):
        build_thumbnail_command("clip.mp4", 1.0, "x", "out.png", box_opacity=1.5)


# --- generate_thumbnail (fake runner) -------------------------------------

class _Result:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_generate_thumbnail_returns_path_on_success(tmp_path):
    captured = {}

    def fake_runner(command, **kwargs):
        captured["command"] = command
        return _Result(0)

    out = tmp_path / "posters" / "thumb.png"
    result = generate_thumbnail("clip.mp4", "WIN", str(out), timestamp=5.0, runner=fake_runner)
    assert result == str(out)
    assert out.parent.exists()  # parent dir created
    assert captured["command"][0] == "ffmpeg"


def test_generate_thumbnail_raises_on_ffmpeg_failure(tmp_path):
    def fake_runner(command, **kwargs):
        return _Result(1, stderr="boom")

    with pytest.raises(ThumbnailError, match="ffmpeg failed"):
        generate_thumbnail("clip.mp4", "x", str(tmp_path / "t.png"), timestamp=1.0, runner=fake_runner)
