import json

import pytest

from scripts.render import (
    RenderError,
    VALID_TRANSITIONS,
    ass_color,
    build_ass_content,
    build_audio_filter_chain,
    build_compilation_command,
    build_ffmpeg_command,
    build_jumpcut_command,
    build_profanity_mask_filter,
    build_punch_zoom_filter,
    build_subtitle_force_style,
    build_transition_filter,
    clamp_clip_bounds,
    compute_crop_filter,
    compute_subtitle_margin_v,
    probe_video,
    render_clip,
    SUBTITLE_MARGIN_V,
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


def test_compute_subtitle_margin_v_top_and_center_passthrough():
    assert compute_subtitle_margin_v("top", "zoom", src_width=1920, src_height=1080) == SUBTITLE_MARGIN_V["top"]
    assert compute_subtitle_margin_v("center", "pad", src_width=1920, src_height=1080) == SUBTITLE_MARGIN_V["center"]


def test_compute_subtitle_margin_v_zoom_uses_static_bottom_margin():
    assert compute_subtitle_margin_v("bottom", "zoom", src_width=1920, src_height=1080) == SUBTITLE_MARGIN_V["bottom"]


def test_compute_subtitle_margin_v_pad_uses_safe_floor_on_standard_16_9_source():
    # bottom bar is 656px; half of that (328px) is below the 380px safe
    # floor, so the floor wins for a typical 16:9 recording.
    assert compute_subtitle_margin_v("bottom", "pad", src_width=1920, src_height=1080) == 380


def test_compute_subtitle_margin_v_original_16_9_centers_in_large_bottom_bar():
    # an ultra-wide source leaves a big black bar - captions center inside
    # it, well past the 380px safe floor.
    assert compute_subtitle_margin_v("bottom", "original-16:9", src_width=2560, src_height=600) == 416


def test_compute_subtitle_margin_v_rejects_unresolved_auto():
    with pytest.raises(RenderError, match="resolved value"):
        compute_subtitle_margin_v("bottom", "auto", src_width=1920, src_height=1080)


def test_build_ffmpeg_command_without_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0, crop_filter="crop=608:1080:656:0,scale=1080:1920"
    )

    assert command == [
        "ffmpeg", "-y",
        "-loglevel", "error",
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

    assert command[11] == "scale=1080:608,pad=1080:1920:0:394:black,subtitles='work/x/subs.srt'"


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

    assert command[11] == (
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

    assert command[11] == "crop=608:1080:656:0,scale=1080:1920,fade=t=out:st=29.5:d=0.5"
    assert command[12] == "-af"
    assert command[13] == "afade=t=out:st=29.5:d=0.5"
    assert command[-1] == "out.mp4"


def test_build_ffmpeg_command_fade_out_clamped_to_half_clip_duration():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=10.6,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
    )

    assert "fade=t=out:st=0.3:d=0.3" in command[11]


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
    assert "fade=t=out:st=30.0:d=0.5" in command[11]
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
    assert "fade=t=out:st=30.0:d=0.2" in command[11]


def test_build_ffmpeg_command_fade_falls_back_to_overlap_when_no_tail():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
        video_duration=40.0,
    )

    assert command[command.index("-t") + 1] == "30.0"
    assert "fade=t=out:st=29.5:d=0.5" in command[11]


def test_build_ffmpeg_command_without_fade_has_no_audio_filter():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    assert "-af" not in command


def test_build_ffmpeg_command_denoise_only():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        denoise=True,
    )

    assert command[command.index("-af") + 1] == "afftdn=nr=6.0"


def test_build_ffmpeg_command_denoise_custom_strength():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        denoise=True,
        denoise_strength=20.0,
    )

    assert command[command.index("-af") + 1] == "afftdn=nr=20.0"


def test_build_ffmpeg_command_loudnorm_only():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        loudnorm=True,
    )

    assert command[command.index("-af") + 1] == "loudnorm=I=-16:TP=-1.5:LRA=11"


def test_build_ffmpeg_command_denoise_loudnorm_and_fade_chain_in_order():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5,
        denoise=True,
        loudnorm=True,
    )

    assert command[command.index("-af") + 1] == (
        "afftdn=nr=6.0,loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st=29.5:d=0.5"
    )


def test_build_audio_filter_chain_profanity_filter_order_after_loudnorm_before_fade():
    mask = build_profanity_mask_filter([(2.0, 2.4)])

    chain = build_audio_filter_chain(
        denoise=True, loudnorm=True, fade_filter="afade=t=out:st=29.5:d=0.5",
        profanity_filter=mask,
    )

    assert chain == (
        f"afftdn=nr=6.0,loudnorm=I=-16:TP=-1.5:LRA=11,{mask},afade=t=out:st=29.5:d=0.5"
    )


def test_build_audio_filter_chain_none_profanity_filter_unchanged():
    chain = build_audio_filter_chain(
        denoise=True, loudnorm=True, fade_filter="afade=t=out:st=29.5:d=0.5",
        profanity_filter=None,
    )

    assert chain == "afftdn=nr=6.0,loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st=29.5:d=0.5"


def test_build_ffmpeg_command_vignette_applies_after_crop_before_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        subtitles_path="work/x/subs.srt",
        vignette=True,
    )

    assert command[11] == (
        "crop=608:1080:656:0,scale=1080:1920,vignette,subtitles='work/x/subs.srt'"
    )


def test_build_ffmpeg_command_grain_strength_applies():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        grain_strength=25,
    )

    assert command[11] == "crop=608:1080:656:0,scale=1080:1920,noise=alls=25:allf=t"


def test_build_ffmpeg_command_vignette_and_grain_chain_together():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        vignette=True,
        grain_strength=25,
    )

    assert command[11] == (
        "crop=608:1080:656:0,scale=1080:1920,vignette,noise=alls=25:allf=t"
    )


def test_build_ffmpeg_command_grain_strength_out_of_range_raises():
    with pytest.raises(RenderError, match="grain_strength must be between 0 and 100"):
        build_ffmpeg_command(
            "in.mp4", "out.mp4", start=10.0, end=40.0,
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
            grain_strength=150,
        )


def test_build_punch_zoom_filter_shape():
    result = build_punch_zoom_filter(punch_at=5.0, zoom_amount=1.15, ramp=0.25)

    assert result == (
        "crop=w='1080/(if(lt(t,5.0),1,if(lt(t,5.25),1+(1.15-1)*(t-5.0)/0.25,1.15)))':"
        "h='1920/(if(lt(t,5.0),1,if(lt(t,5.25),1+(1.15-1)*(t-5.0)/0.25,1.15)))':"
        "x='(in_w-out_w)/2':y='(in_h-out_h)/2',scale=1080:1920"
    )


def test_build_punch_zoom_filter_rejects_non_positive_zoom():
    with pytest.raises(RenderError, match="zoom_amount must be > 1.0"):
        build_punch_zoom_filter(punch_at=5.0, zoom_amount=1.0)


def test_build_punch_zoom_filter_rejects_non_positive_ramp():
    with pytest.raises(RenderError, match="ramp must be > 0"):
        build_punch_zoom_filter(punch_at=5.0, ramp=0.0)


def test_build_punch_zoom_filter_rejects_negative_punch_at():
    with pytest.raises(RenderError, match="punch_at must be >= 0"):
        build_punch_zoom_filter(punch_at=-1.0)


def test_build_profanity_mask_filter_returns_none_for_empty_spans():
    assert build_profanity_mask_filter([]) is None


def test_build_profanity_mask_filter_two_spans_shape():
    result = build_profanity_mask_filter(
        [(2.0, 2.4), (5.0, 5.6)],
        duck_volume=0.12, garble_freq=1800.0, garble_width_octaves=4.0,
        warble_freq=18.0, warble_depth=0.7,
    )

    assert result == (
        "volume=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':volume=0.12,"
        "bandreject=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':f=1800.0:width_type=o:w=4.0,"
        "tremolo=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':f=18.0:d=0.7"
    )


def test_build_profanity_mask_filter_rejects_duck_volume_out_of_range():
    with pytest.raises(RenderError, match="duck_volume must be between 0 and 1"):
        build_profanity_mask_filter([(2.0, 2.4)], duck_volume=1.0)


def test_build_profanity_mask_filter_rejects_duck_volume_zero():
    with pytest.raises(RenderError, match="duck_volume must be between 0 and 1"):
        build_profanity_mask_filter([(2.0, 2.4)], duck_volume=0.0)


def test_build_profanity_mask_filter_rejects_negative_span_start():
    with pytest.raises(RenderError, match="invalid profanity span"):
        build_profanity_mask_filter([(-1.0, 2.4)])


def test_build_profanity_mask_filter_rejects_end_before_start():
    with pytest.raises(RenderError, match="invalid profanity span"):
        build_profanity_mask_filter([(2.4, 2.0)])


def test_build_ffmpeg_command_punch_zoom_at_applies_before_effects_and_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        subtitles_path="work/x/subs.srt",
        vignette=True,
        punch_zoom_at=5.0,
    )

    assert command[11] == (
        "crop=608:1080:656:0,scale=1080:1920,"
        + build_punch_zoom_filter(5.0)
        + ",vignette,subtitles='work/x/subs.srt'"
    )


def test_build_ffmpeg_command_no_punch_zoom_by_default():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    assert "crop=w=" not in command[11]


def test_build_jumpcut_command_single_segment_matches_plain_trim_concat():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    assert command[:6] == ["ffmpeg", "-y", "-loglevel", "error", "-ss", "10.0"]
    assert command[command.index("-i") + 1] == "in.mp4"
    assert command[command.index("-t") + 1] == "30.0"

    filter_complex = command[command.index("-filter_complex") + 1]
    assert filter_complex == (
        "[0:v]trim=start=0.0:end=30.0,setpts=PTS-STARTPTS[v0];"
        "[0:a]atrim=start=0.0:end=30.0,asetpts=PTS-STARTPTS[a0];"
        "[v0][a0]concat=n=1:v=1:a=1[vcat][acat];"
        "[vcat]crop=608:1080:656:0,scale=1080:1920[vout];"
        "[acat]anull[aout]"
    )
    assert command[-1] == "out.mp4"
    assert "[vout]" in command
    assert "[aout]" in command


def test_build_jumpcut_command_multiple_segments_trims_and_concats_each():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[0:v]trim=start=0.0:end=10.0,setpts=PTS-STARTPTS[v0]" in filter_complex
    assert "[0:v]trim=start=12.0:end=30.0,setpts=PTS-STARTPTS[v1]" in filter_complex
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vcat][acat]" in filter_complex


def test_build_jumpcut_command_applies_denoise_loudnorm_and_fade_to_acat():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=0.0, clip_end=10.0,
        keep_segments=[(0.0, 10.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        fade_seconds=0.5, denoise=True, loudnorm=True,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[acat]afftdn=nr=6.0,loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st=9.5:d=0.5[aout]" in filter_complex
    assert "[vcat]crop=608:1080:656:0,scale=1080:1920,fade=t=out:st=9.5:d=0.5[vout]" in filter_complex


def test_build_jumpcut_command_rejects_empty_keep_segments():
    with pytest.raises(RenderError, match="keep_segments must not be empty"):
        build_jumpcut_command(
            "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
            keep_segments=[],
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
        )


def test_build_transition_filter_crossfade_returns_xfade_fade_node():
    result = build_transition_filter("crossfade", duration=0.35, offset=1.2, in_a="vA", in_b="vB", out_label="vout")

    assert result == "[vA][vB]xfade=transition=fade:duration=0.35:offset=1.2[vout]"


def test_build_transition_filter_whip_pan_returns_xfade_hblur_node():
    result = build_transition_filter("whip_pan", duration=0.35, offset=1.2, in_a="vA", in_b="vB", out_label="vout")

    assert result == "[vA][vB]xfade=transition=hblur:duration=0.35:offset=1.2[vout]"


def test_build_transition_filter_mask_wipe_returns_xfade_wipeleft_node():
    result = build_transition_filter("mask_wipe", duration=0.35, offset=1.2, in_a="vA", in_b="vB", out_label="vout")

    assert result == "[vA][vB]xfade=transition=wipeleft:duration=0.35:offset=1.2[vout]"


def test_build_transition_filter_glitch_returns_pixelize_chain_with_rgbashift_and_noise():
    result = build_transition_filter("glitch", duration=0.2, offset=1.0, in_a="vA", in_b="vB", out_label="vout")

    assert result.startswith("[vA][vB]xfade=transition=pixelize:duration=0.2:offset=1.0,")
    assert "rgbashift=rh=8:bh=-8:edge=smear" in result
    assert "noise=alls=25:allf=t+u" in result
    assert result.endswith("[vout]")


def test_build_transition_filter_cut_returns_none():
    assert build_transition_filter("cut", duration=0.35, offset=1.0, in_a="vA", in_b="vB", out_label="vout") is None


def test_build_transition_filter_match_cut_returns_none():
    assert build_transition_filter(
        "match_cut", duration=0.35, offset=1.0, in_a="vA", in_b="vB", out_label="vout"
    ) is None


def test_build_transition_filter_rejects_unknown_transition_type():
    with pytest.raises(RenderError, match="transition_type must be one of"):
        build_transition_filter("teleport", duration=0.35, offset=1.0, in_a="vA", in_b="vB", out_label="vout")


def test_build_transition_filter_rejects_non_positive_duration():
    with pytest.raises(RenderError, match="duration must be > 0"):
        build_transition_filter("crossfade", duration=0.0, offset=1.0, in_a="vA", in_b="vB", out_label="vout")


def test_build_transition_filter_rejects_negative_offset():
    with pytest.raises(RenderError, match="offset must be >= 0"):
        build_transition_filter("crossfade", duration=0.35, offset=-0.1, in_a="vA", in_b="vB", out_label="vout")


def test_valid_transitions_matches_transitions_module_canonical_enum():
    # Drift guard: render.py duplicates VALID_TRANSITIONS (rather than importing
    # scripts.transitions) so it stays runnable as a standalone CLI without a
    # sys.path insert - this test catches the two enums silently diverging.
    from scripts.transitions import TRANSITION_TYPES

    assert VALID_TRANSITIONS == TRANSITION_TYPES


def test_build_jumpcut_command_all_cut_boundary_transitions_matches_flat_concat():
    # backward compatibility: explicit all-cut boundary_transitions must produce
    # the exact same flat-concat graph as omitting the param entirely.
    command_with_none = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )
    command_with_cut = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["cut"], boundary_gaps=[2.0],
    )

    assert command_with_cut == command_with_none


def test_build_jumpcut_command_all_match_cut_boundary_transitions_matches_flat_concat():
    command_with_none = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )
    command_with_match_cut = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["match_cut"], boundary_gaps=[2.0],
    )

    assert command_with_match_cut == command_with_none


def test_build_jumpcut_command_forced_crossfade_transition_emits_xfade_and_acrossfade():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["crossfade"], boundary_gaps=[2.0],
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=fade" in filter_complex
    assert "acrossfade=d=" in filter_complex
    assert "[vout]" in filter_complex
    assert "[aout]" in filter_complex


def test_build_jumpcut_command_forced_whip_pan_transition_emits_hblur():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["whip_pan"], boundary_gaps=[2.0],
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=hblur" in filter_complex


def test_build_jumpcut_command_forced_glitch_transition_emits_pixelize_and_rgbashift():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["glitch"], boundary_gaps=[2.0],
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=pixelize" in filter_complex
    assert "rgbashift" in filter_complex


def test_build_jumpcut_command_transition_falls_back_to_concat_when_gap_below_min_overlap():
    command = build_jumpcut_command(
        "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
        keep_segments=[(10.0, 20.0), (22.0, 40.0)],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["crossfade"], boundary_gaps=[0.05],
        min_overlap_seconds=0.12,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "xfade" not in filter_complex
    assert "concat=n=2:v=1:a=1" in filter_complex


def test_build_jumpcut_command_rejects_unknown_boundary_transition_type():
    with pytest.raises(RenderError, match="boundary_transitions"):
        build_jumpcut_command(
            "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
            keep_segments=[(10.0, 20.0), (22.0, 40.0)],
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
            boundary_transitions=["teleport"], boundary_gaps=[2.0],
        )


def test_build_compilation_command_rejects_empty_members():
    with pytest.raises(RenderError, match="members must not be empty"):
        build_compilation_command(
            "in.mp4", "out.mp4", members=[],
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
        )


def test_build_compilation_command_rejects_single_member():
    with pytest.raises(RenderError, match="a compilation needs >= 2 members"):
        build_compilation_command(
            "in.mp4", "out.mp4", members=[{"start": 0.0, "end": 5.0}],
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
        )


def test_build_compilation_command_builds_one_input_per_member_two_members():
    command = build_compilation_command(
        "in.mp4", "out.mp4",
        members=[{"start": 10.0, "end": 15.0}, {"start": 50.0, "end": 55.0}],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    assert command.count("-i") == 2
    assert command.count("-ss") == 2


def test_build_compilation_command_builds_one_input_per_member_three_members():
    command = build_compilation_command(
        "in.mp4", "out.mp4",
        members=[
            {"start": 10.0, "end": 15.0},
            {"start": 50.0, "end": 55.0},
            {"start": 90.0, "end": 92.0},
        ],
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )

    assert command.count("-i") == 3
    assert command.count("-ss") == 3


def test_build_compilation_command_rejects_unknown_boundary_transition():
    with pytest.raises(RenderError, match="boundary_transitions entries must be one of"):
        build_compilation_command(
            "in.mp4", "out.mp4",
            members=[{"start": 10.0, "end": 15.0}, {"start": 50.0, "end": 55.0}],
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
            boundary_transitions=["teleport"],
        )


def test_build_compilation_command_all_cut_boundary_transitions_matches_no_transitions():
    members = [{"start": 10.0, "end": 15.0}, {"start": 50.0, "end": 55.0}]

    command_with_none = build_compilation_command(
        "in.mp4", "out.mp4", members=members,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )
    command_with_cut = build_compilation_command(
        "in.mp4", "out.mp4", members=members,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["cut"],
    )

    assert command_with_cut == command_with_none


def test_build_compilation_command_forced_crossfade_boundary_emits_xfade_without_trim_extension():
    members = [{"start": 10.0, "end": 15.0}, {"start": 50.0, "end": 55.0}]

    no_transition_command = build_compilation_command(
        "in.mp4", "out.mp4", members=members,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
    )
    crossfade_command = build_compilation_command(
        "in.mp4", "out.mp4", members=members,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["crossfade"],
    )

    no_transition_filter = no_transition_command[no_transition_command.index("-filter_complex") + 1]
    crossfade_filter = crossfade_command[crossfade_command.index("-filter_complex") + 1]

    # trims for the two adjacent segments are unchanged from the no-transition
    # case - only the xfade offset differs, no gap-borrowed trim-extension.
    assert "[0:v]trim=start=0.0:end=5.0,setpts=PTS-STARTPTS[v0]" in no_transition_filter
    assert "[1:v]trim=start=0.0:end=5.0,setpts=PTS-STARTPTS[v1]" in no_transition_filter
    assert "[0:v]trim=start=0.0:end=5.0,setpts=PTS-STARTPTS[v0]" in crossfade_filter
    assert "[1:v]trim=start=0.0:end=5.0,setpts=PTS-STARTPTS[v1]" in crossfade_filter
    assert "xfade=transition=fade" in crossfade_filter
    assert "acrossfade=d=" in crossfade_filter


def test_build_compilation_command_member_with_keep_segments_flattens_extra_boundary():
    members = [
        {"start": 10.0, "end": 20.0, "keep_segments": [[10.0, 13.0], [15.0, 20.0]]},
        {"start": 50.0, "end": 55.0},
    ]

    # 2 members, but 3 flattened segments (member 0's 2 keep_segments + member
    # 1's single window) - a 2-entry boundary_transitions list is required.
    command = build_compilation_command(
        "in.mp4", "out.mp4", members=members,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        boundary_transitions=["cut", "cut"],
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=1" in filter_complex


def test_build_compilation_command_rejects_mismatched_boundary_transitions_length():
    members = [
        {"start": 10.0, "end": 20.0, "keep_segments": [[10.0, 13.0], [15.0, 20.0]]},
        {"start": 50.0, "end": 55.0},
    ]

    with pytest.raises(RenderError, match="boundary_transitions length"):
        build_compilation_command(
            "in.mp4", "out.mp4", members=members,
            crop_filter="crop=608:1080:656:0,scale=1080:1920",
            boundary_transitions=["cut"],
        )


def test_build_compilation_command_applies_crop_subtitles_fade_exactly_once(tmp_path):
    subs_path = tmp_path / "subs.ass"
    subs_path.write_text("dummy", encoding="utf-8")
    members = [{"start": 10.0, "end": 15.0}, {"start": 50.0, "end": 55.0}]

    command = build_compilation_command(
        "in.mp4", "out.mp4", members=members,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        subtitles_path=str(subs_path),
        fade_seconds=0.5,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert filter_complex.count("crop=608:1080:656:0,scale=1080:1920") == 1
    assert filter_complex.count("subtitles=") == 1
    # one video fade=t=out (vcat) and one audio afade=t=out (acat) - not
    # duplicated per member (2 members would show 4 if it were).
    assert filter_complex.count("d=0.5") == 2


def test_build_ffmpeg_command_no_audio_flags_has_no_audio_filter():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="crop=608:1080:656:0,scale=1080:1920",
        denoise=False,
        loudnorm=False,
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


def test_render_clip_reads_punch_zoom_at_from_plan_entry():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom", "punch_zoom_at": 5.0}

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=lambda command, capture_output, text: FakeResult(),
    )

    video_filter = command[command.index("-vf") + 1]
    assert "crop=w='1080/" in video_filter


def test_render_clip_rejects_punch_zoom_at_on_pad_crop_style():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "pad", "punch_zoom_at": 5.0}

    with pytest.raises(RenderError, match="punch_zoom_at requires crop_style='zoom'"):
        render_clip(
            "in.mp4", "out.mp4", plan_entry,
            video_duration=100.0, src_width=1920, src_height=1080,
            runner=lambda command, capture_output, text: FakeResult(),
        )


def test_render_clip_rejects_punch_zoom_at_on_original_16_9_crop_style():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "original-16:9", "punch_zoom_at": 5.0}

    with pytest.raises(RenderError, match="punch_zoom_at requires crop_style='zoom'"):
        render_clip(
            "in.mp4", "out.mp4", plan_entry,
            video_duration=100.0, src_width=1920, src_height=1080,
            runner=lambda command, capture_output, text: FakeResult(),
        )


def test_render_clip_without_punch_zoom_at_has_no_zoom_filter():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom"}

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=lambda command, capture_output, text: FakeResult(),
    )

    video_filter = command[command.index("-vf") + 1]
    assert "crop=w='" not in video_filter


def test_render_clip_uses_jumpcut_command_when_keep_segments_present():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {
        "start": 10.0, "end": 40.0, "crop_style": "zoom",
        "keep_segments": [[10.0, 20.0], [22.0, 40.0]],
    }

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=lambda command, capture_output, text: FakeResult(),
    )

    assert "-filter_complex" in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1" in filter_complex


def test_render_clip_threads_boundary_transitions_into_jumpcut_command():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {
        "start": 10.0, "end": 40.0, "crop_style": "zoom",
        "keep_segments": [[10.0, 20.0], [22.0, 40.0]],
        "boundary_transitions": ["crossfade"],
    }

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=lambda command, capture_output, text: FakeResult(),
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "xfade" in filter_complex


def test_render_clip_rejects_boundary_transitions_wrong_length():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {
        "start": 10.0, "end": 40.0, "crop_style": "zoom",
        "keep_segments": [[10.0, 20.0], [22.0, 40.0]],
        "boundary_transitions": ["crossfade", "crossfade"],
    }

    with pytest.raises(RenderError, match="boundary_transitions"):
        render_clip(
            "in.mp4", "out.mp4", plan_entry,
            video_duration=100.0, src_width=1920, src_height=1080,
            runner=lambda command, capture_output, text: FakeResult(),
        )


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
    assert "fade=t=out:st=30.0:d=0.5" in command[11]


def test_build_ass_content_sets_play_res_to_canvas_size():
    cues = [{"start": 0.26, "end": 2.18, "text": "hello world"}]

    ass = build_ass_content(cues, "Arial Black", 92, "white", "black", "yellow", "bottom", 380, 1080, 1920)

    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Alignment=2" not in ass  # baked into the Style line, not a force_style override
    assert "Style: Default,Arial Black,92,&H00FFFFFF,&H0000FFFF,&H00000000," in ass
    # Style line is positional CSV (MarginL, MarginR, MarginV, Encoding), not key=value,
    # so verify margin_v=380 lands in the MarginV slot rather than searching for "MarginV=380".
    assert "10,10,380,1\n" in ass
    assert "Dialogue: 0,0:00:00.26,0:00:02.18,Default,,0,0,0,,hello world" in ass


def test_build_ass_content_escapes_newlines_as_hard_breaks():
    cues = [{"start": 0.0, "end": 1.0, "text": "line one\nline two"}]

    ass = build_ass_content(cues, "Arial", 48, "white", "black", "yellow", "top", 120, 1080, 1920)

    assert "line one\\Nline two" in ass


def test_build_ass_content_karaoke_cue_emits_base_plus_per_word_overlay_events():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]
    cues = [{"start": 0.0, "end": 1.0, "text": "hello world", "words": words}]

    ass = build_ass_content(cues, "Arial Black", 92, "white", "black", "yellow", "bottom", 380, 1080, 1920)

    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hello world" in ass
    assert "Dialogue: 1,0:00:00.00,0:00:00.40,Default,,0,0,0," in ass
    assert "Dialogue: 1,0:00:00.50,0:00:01.00,Default,,0,0,0," in ass
    # first overlay (word 0 active): "hello" opaque+highlighted, "world" transparent
    first_overlay = [line for line in ass.splitlines() if line.startswith("Dialogue: 1,0:00:00.00,0:00:00.40")][0]
    assert "\\alpha&H00&\\c&H0000FFFF&}hello" in first_overlay
    assert "\\alpha&HFF&}world" in first_overlay
    # second overlay (word 1 active): "world" opaque+highlighted, "hello" transparent
    second_overlay = [line for line in ass.splitlines() if line.startswith("Dialogue: 1,0:00:00.50,0:00:01.00")][0]
    assert "\\alpha&HFF&}hello" in second_overlay
    assert "\\alpha&H00&\\c&H0000FFFF&}world" in second_overlay


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
        "font": "Arial Black", "size": 92, "color": "white",
        "outline_color": "black", "highlight_color": "yellow",
        "position": "bottom", "words_per_cue": 4,
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


def test_render_clip_uses_karaoke_words_json_when_present(tmp_path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello world\n\n", encoding="utf-8"
    )
    words_path = tmp_path / "subs_words.json"
    words_path.write_text(
        json.dumps([
            {"word": "hello", "start": 0.0, "end": 0.4},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]),
        encoding="utf-8",
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
        "font": "Arial Black", "size": 92, "color": "white", "outline_color": "black",
        "highlight_color": "yellow", "position": "bottom", "words_per_cue": 4,
    }

    render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        subtitle_style=subtitle_style,
        runner=fake_runner,
    )

    ass_content = srt_path.with_suffix(".ass").read_text(encoding="utf-8")
    assert "Dialogue: 1," in ass_content  # per-word overlay events present
    assert "\\c&H0000FFFF&" in ass_content  # highlight color applied somewhere
    assert "hello" in ass_content
    assert "world" in ass_content


def test_render_clip_computes_frame_relative_margin_for_pad_crop_style(tmp_path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello world\n\n", encoding="utf-8"
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
        "start": 10.0, "end": 40.0, "crop_style": "pad",
        "subtitles_path": str(srt_path),
    }
    subtitle_style = {
        "font": "Arial Black", "size": 92, "color": "white", "outline_color": "black",
        "highlight_color": "yellow", "position": "bottom", "words_per_cue": 4,
    }

    render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        subtitle_style=subtitle_style,
        runner=fake_runner,
    )

    ass_content = srt_path.with_suffix(".ass").read_text(encoding="utf-8")
    # pad crop on a 1920x1080 source: bottom bar 656px, half=328 < 380 safe floor -> 380 wins,
    # same numeric value as zoom's static margin, but reached via the geometry branch this time.
    assert "10,10,380,1\n" in ass_content


def test_render_clip_dispatches_to_build_compilation_command_for_type_compilation():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    plan_entry = {
        "type": "compilation",
        "crop_style": "zoom",
        "segments": [
            {"start": 10.0, "end": 15.0},
            {"start": 50.0, "end": 55.0},
        ],
    }

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=lambda command, capture_output, text: FakeResult(),
    )

    assert command.count("-i") == 2


def test_render_clip_compilation_entry_without_top_level_start_end_does_not_raise_key_error():
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    # deliberately no top-level "start"/"end" keys - regression proof for the
    # render_clip reordering (compilation entries only have per-member bounds)
    plan_entry = {
        "type": "compilation",
        "crop_style": "zoom",
        "segments": [
            {"start": 10.0, "end": 15.0},
            {"start": 50.0, "end": 55.0},
        ],
    }

    render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=lambda command, capture_output, text: FakeResult(),
    )


def test_render_clip_compilation_entry_with_empty_segments_raises_render_error():
    plan_entry = {"type": "compilation", "crop_style": "zoom", "segments": []}

    with pytest.raises(RenderError, match="segments"):
        render_clip(
            "in.mp4", "out.mp4", plan_entry,
            video_duration=100.0, src_width=1920, src_height=1080,
            runner=lambda command, capture_output, text: FakeResult(),
        )


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
