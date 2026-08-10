import json
import os
import re
import subprocess
import sys
from pathlib import Path

from scripts.jumpcuts import remap_words
from scripts.profanity import (
    compile_patterns,
    find_profane_spans,
    load_wordlist,
    mask_cues,
    mask_token,
    normalize_word,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WORDLIST_PATH = str(REPO_ROOT / "data" / "profanity_wordlist.yaml")

_TEST_WORDLIST = {
    "normalize": {
        "substitutions": {"0": "о", "3": "е"},
        "collapse_repeats": True,
        "strip_chars": "*_-.",
    },
    "ru": [{"root": "бля"}],
    "en": [{"root": "fuck"}],
}


# --- load_wordlist (fail-open, D-04) ---------------------------------------


def test_load_wordlist_missing_file_returns_empty_and_warns(capsys):
    result = load_wordlist("nonexistent/path/to/wordlist.yaml")

    assert result == {"updated": "unknown", "normalize": {}, "ru": [], "en": []}
    captured = capsys.readouterr()
    assert "[warn]" in captured.err
    assert "continuing with an empty wordlist" in captured.err


def test_load_wordlist_malformed_yaml_returns_empty_and_warns(tmp_path, capsys):
    bad_file = tmp_path / "malformed.yaml"
    # Unbalanced flow-mapping - invalid YAML, must not raise.
    bad_file.write_text("ru: [{root: \"bad\"\n", encoding="utf-8")

    result = load_wordlist(str(bad_file))

    assert result == {"updated": "unknown", "normalize": {}, "ru": [], "en": []}
    captured = capsys.readouterr()
    assert "[warn]" in captured.err


def test_load_wordlist_valid_file_defaults_updated_to_unknown_when_absent(tmp_path):
    valid_file = tmp_path / "wordlist.yaml"
    valid_file.write_text("ru:\n  - root: \"bla\"\n", encoding="utf-8")

    result = load_wordlist(str(valid_file))

    assert result["updated"] == "unknown"
    assert result["ru"] == [{"root": "bla"}]


def test_load_wordlist_valid_file_never_raises_on_normal_input():
    # Sanity check the real shipped path loads without raising - full
    # shipped-file assertions live in the "wordlist_file"/"shipped" tests
    # added by Task 3.
    result = load_wordlist(WORDLIST_PATH)
    assert isinstance(result, dict)


# --- normalize_word (obfuscation handling, D-02) ----------------------------


def test_normalize_word_applies_substitutions_strip_and_collapse():
    normalize_cfg = {
        "substitutions": {"0": "o", "3": "e"},
        "collapse_repeats": True,
        "strip_chars": "*_-.",
    }

    assert normalize_word("fu*ck", normalize_cfg) == "fuck"
    assert normalize_word("sh1t", {"substitutions": {"1": "i"}}) == "shit"


def test_normalize_word_collapses_repeated_chars_leetspeak():
    normalize_cfg = {
        "substitutions": {"0": "о"},
        "collapse_repeats": True,
        "strip_chars": "",
    }

    assert normalize_word("бляяя", normalize_cfg) == "бля"
    assert normalize_word("fuuuuck", normalize_cfg) == "fuck"


def test_normalize_word_case_folds_before_matching():
    normalize_cfg = {"substitutions": {}, "collapse_repeats": False, "strip_chars": ""}

    assert normalize_word("FUCK", normalize_cfg) == "fuck"


# --- compile_patterns (word-boundary + ReDoS guard, ASVS V5) ---------------


def test_compile_patterns_escapes_root_and_rejects_non_boundary_match():
    # "облако" ("cloud") contains the "бл" substring mid-word, NOT at a word
    # boundary - must not match (Pitfall 1).
    wordlist = {"ru": [{"root": "бл"}], "en": []}
    patterns = compile_patterns(wordlist)

    assert not any(pattern.search("облако") for pattern in patterns)
    assert any(pattern.search("бля") for pattern in patterns)


def test_compile_patterns_treats_raw_regex_root_as_literal_not_backtracking():
    # A malicious/malformed wordlist entry containing raw regex metachars
    # must be compiled as a LITERAL string (re.escape), never as live
    # regex syntax - this is the ReDoS guard (ASVS V5).
    wordlist = {"ru": [{"root": "(a+)+"}], "en": []}
    patterns = compile_patterns(wordlist)

    assert len(patterns) == 1
    # Would hang under catastrophic backtracking if compiled as a raw
    # regex; completes instantly and finds no match since the literal
    # string "(a+)+" is not present.
    assert patterns[0].search("a" * 40 + "!") is None
    assert re.escape("(a+)+") in patterns[0].pattern


def test_compile_patterns_compiles_one_pattern_per_root_across_ru_and_en():
    wordlist = {"ru": [{"root": "бля"}, {"root": "хуй"}], "en": [{"root": "fuck"}]}

    patterns = compile_patterns(wordlist)

    assert len(patterns) == 3


# --- find_profane_spans (pad + merge + span-cap fail-open) -----------------


def test_find_profane_spans_detects_ru_en_and_obfuscated_stems():
    words = [
        {"word": "привет", "start": 0.0, "end": 0.4},
        {"word": "бляяя,", "start": 0.5, "end": 0.9},
        {"word": "fu_ck", "start": 1.0, "end": 1.3},
        {"word": "чисто", "start": 1.4, "end": 1.7},
    ]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0)

    assert spans == [(0.5, 0.9), (1.0, 1.3)]


def test_find_profane_spans_widens_a_zero_length_whisper_word():
    # faster-whisper emits start == end often enough that it killed a whole
    # render pass on 2026-08-10 ("блять." at 6.3-6.3): with pad/onset at their
    # 0 defaults the span stayed empty and render.py rejected it.
    words = [
        {"word": "ну", "start": 6.0, "end": 6.3},
        {"word": "блять.", "start": 6.3, "end": 6.3},
        {"word": "ладно", "start": 7.0, "end": 7.4},
    ]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0)

    assert len(spans) == 1
    start, end = spans[0]
    assert start == 6.3
    assert end - start >= 0.12
    assert end <= 7.0


def test_find_profane_spans_widens_a_zero_length_word_backwards_when_boxed_in():
    # Next word starts on the same timestamp, so the only room is behind it.
    words = [
        {"word": "бляяя,", "start": 1.0, "end": 1.0},
        {"word": "дальше", "start": 1.0, "end": 1.4},
    ]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0)

    assert spans == [(0.88, 1.0)]


def test_find_profane_spans_skips_a_zero_length_word_with_no_room(capsys):
    # Boxed in on both sides: previous word ends where the clip does.
    words = [
        {"word": "ну", "start": 0.5, "end": 1.0},
        {"word": "бляяя,", "start": 1.0, "end": 1.0},
    ]

    assert find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0, clip_duration=1.0) == []
    assert "zero-length span" in capsys.readouterr().err


def test_find_profane_spans_no_matches_returns_empty_list():
    words = [{"word": "clean", "start": 0.0, "end": 0.3}]

    assert find_profane_spans(words, _TEST_WORDLIST) == []


def test_find_profane_spans_pads_and_clamps_span_bounds():
    words = [{"word": "fuck", "start": 0.02, "end": 5.97}]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.08, clip_duration=6.0)

    # start clamps to >= 0, end clamps to <= clip_duration
    assert spans == [(0.0, 6.0)]


def test_find_profane_spans_merges_overlapping_padded_spans():
    words = [
        {"word": "fuck", "start": 1.0, "end": 1.2},
        {"word": "бля", "start": 1.25, "end": 1.4},
    ]

    # pad_seconds=0.1 makes the two padded spans (0.9,1.3) and (1.15,1.5)
    # overlap - they must merge into a single span.
    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.1)

    assert spans == [(0.9, 1.5)]


def test_find_profane_spans_end_pad_clamps_to_next_word_start():
    words = [
        {"word": "fuck", "start": 1.0, "end": 1.2},
        {"word": "чисто", "start": 1.28, "end": 1.6},
    ]

    # pad_seconds=0.2 would push the end to 1.4, well past the next word's
    # own start (1.28) - the beep must stop at that boundary instead of
    # eating into "чисто".
    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.2)

    assert spans == [(0.8, 1.28)]


def test_find_profane_spans_start_pad_clamps_to_previous_word_end():
    words = [
        {"word": "привет", "start": 0.5, "end": 0.9},
        {"word": "fuck", "start": 0.95, "end": 1.2},
    ]

    # pad_seconds=0.2 would pull the start back to 0.75, into the previous
    # word's own span (ends 0.9) - must clamp at 0.9 instead.
    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.2)

    assert spans == [(0.9, 1.4)]


def test_find_profane_spans_neighbor_clamp_never_shrinks_below_word_bounds():
    # Neighbor words sit right against the profane word's own timestamps
    # (no gap at all) - the clamp must still cover the full word itself,
    # never crossing below its own start/above its own end.
    words = [
        {"word": "привет", "start": 0.5, "end": 1.0},
        {"word": "fuck", "start": 1.0, "end": 1.2},
        {"word": "чисто", "start": 1.2, "end": 1.6},
    ]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.2)

    assert spans == [(1.0, 1.2)]


def test_find_profane_spans_remap_dropped_word_is_absent():
    # Absolute source-file timestamps, one profane word falls entirely
    # inside a cut jump-cut gap (20.0-25.0).
    absolute_words = [
        {"word": "fuck", "start": 12.0, "end": 12.3},
        {"word": "fuck", "start": 22.0, "end": 22.3},
    ]
    keep_segments = [(10.0, 20.0), (25.0, 40.0)]

    remapped = remap_words(absolute_words, keep_segments)
    spans = find_profane_spans(remapped, _TEST_WORDLIST, pad_seconds=0.0)

    # Only the first word (kept) survives remap_words; profanity.py never
    # reimplements the remap itself (Pattern 2) - it just sees a shorter
    # words list.
    assert len(remapped) == 1
    assert spans == [(2.0, 2.3)]


def test_find_profane_spans_span_cap_fail_open_returns_empty_and_warns(capsys):
    words = [
        {"word": "fuck", "start": 0.0, "end": 0.2},
        {"word": "бля", "start": 5.0, "end": 5.2},
    ]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0, max_spans=1)

    assert spans == []
    captured = capsys.readouterr()
    assert "[warn]" in captured.err
    assert "exceeds cap" in captured.err


# --- find_profane_spans onset_seconds ---------------------------------------


def test_find_profane_spans_onset_zero_matches_default_behavior():
    words = [{"word": "fuck", "start": 1.0, "end": 1.3}]

    spans_default = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.08)
    spans_onset_zero = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.08, onset_seconds=0.0)

    assert spans_default == spans_onset_zero == [(0.92, 1.38)]


def test_find_profane_spans_onset_shifts_start_no_pad_subtraction():
    words = [{"word": "fuck", "start": 1.0, "end": 1.3}]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.08, onset_seconds=0.12)

    # start = word_start + onset (no pad subtracted); end unchanged (+pad).
    assert spans == [(1.12, 1.38)]


def test_find_profane_spans_onset_degenerate_masks_whole_word():
    words = [{"word": "fuck", "start": 1.0, "end": 1.1}]

    # onset (0.5) >= word_duration (0.1) -> whole-word fallback, never past
    # word end.
    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0, onset_seconds=0.5)

    assert spans == [(1.0, 1.1)]


# --- CLI wrapper -------------------------------------------------------------


def _run_cli(args):
    return subprocess.run(
        [sys.executable, "scripts/profanity.py", *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_cli_prints_spans_json_and_capturable_last_line(tmp_path):
    words_path = tmp_path / "words.json"
    words_path.write_text(json.dumps([{"word": "fuck", "start": 1.0, "end": 1.2}]), encoding="utf-8")
    wordlist_path = tmp_path / "wordlist.yaml"
    wordlist_path.write_text("en:\n  - root: \"fuck\"\n", encoding="utf-8")

    result = _run_cli(
        [str(words_path), "--wordlist", str(wordlist_path), "--pad-seconds", "0"]
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    spans = json.loads(lines[0])
    assert spans == [[1.0, 1.2]]
    assert lines[-1] == str(words_path)


def test_cli_threads_onset_seconds_into_find_profane_spans(tmp_path):
    words_path = tmp_path / "words.json"
    words_path.write_text(json.dumps([{"word": "fuck", "start": 1.0, "end": 1.3}]), encoding="utf-8")
    wordlist_path = tmp_path / "wordlist.yaml"
    wordlist_path.write_text("en:\n  - root: \"fuck\"\n", encoding="utf-8")

    result = _run_cli(
        [str(words_path), "--wordlist", str(wordlist_path), "--pad-seconds", "0.08", "--onset-seconds", "0.12"]
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    spans = json.loads(lines[0])
    assert spans == [[1.12, 1.38]]


# --- shipped data/profanity_wordlist.yaml (D-01, committed data file) ------


def test_shipped_wordlist_file_loads_with_normalize_ru_en():
    wordlist = load_wordlist(WORDLIST_PATH)

    assert wordlist["updated"] != "unknown"
    assert "normalize" in wordlist
    assert wordlist["ru"], "expected at least one RU stem"
    assert wordlist["en"], "expected at least one EN stem"


def test_shipped_wordlist_file_detects_known_stem_and_ignores_clean_word():
    wordlist = load_wordlist(WORDLIST_PATH)
    words = [
        {"word": "fuck", "start": 1.0, "end": 1.3},
        {"word": "clean", "start": 2.0, "end": 2.3},
    ]

    spans = find_profane_spans(words, wordlist, pad_seconds=0.0)

    assert spans == [(1.0, 1.3)]


# --- mask_token (partial subtitle mask) ------------------------------------


def test_mask_token_keeps_prefix_masks_rest():
    # keep_ratio 0.4: round(3*0.4)=1 kept, round(7*0.4)=3 kept.
    assert mask_token("хуй", 0.4) == "х**"
    assert mask_token("пидорас", 0.4) == "пид****"


def test_mask_token_always_masks_at_least_one_char():
    # High ratio must still mask the final char (never leave a word intact).
    assert mask_token("бля", 1.0) == "бл*"


def test_mask_token_single_char_unchanged():
    assert mask_token("х", 0.4) == "х"


def test_mask_token_preserves_length():
    masked = mask_token("блядь", 0.4)
    assert len(masked) == len("блядь")


# --- mask_cues (text + karaoke word tokens) --------------------------------


def test_mask_cues_masks_text_and_word_tokens():
    cues = [
        {
            "text": "ну ты бля даёшь",
            "start": 0.0,
            "end": 1.0,
            "words": [
                {"word": "ну", "start": 0.0, "end": 0.2},
                {"word": "ты", "start": 0.2, "end": 0.4},
                {"word": "бля", "start": 0.4, "end": 0.7},
                {"word": "даёшь", "start": 0.7, "end": 1.0},
            ],
        }
    ]

    masked = mask_cues(cues, _TEST_WORDLIST, keep_ratio=0.4)

    assert masked[0]["text"] == "ну ты б** даёшь"
    assert [w["word"] for w in masked[0]["words"]] == ["ну", "ты", "б**", "даёшь"]


def test_mask_cues_masks_word_with_trailing_punctuation():
    cues = [{"text": "fuck!", "start": 0.0, "end": 1.0}]

    masked = mask_cues(cues, _TEST_WORDLIST, keep_ratio=0.4)

    # Regex masks only the \w+ run; '!' is preserved.
    assert masked[0]["text"] == "fu**!"


def test_mask_cues_does_not_mutate_input():
    cues = [{"text": "бля", "start": 0.0, "end": 1.0, "words": [{"word": "бля"}]}]

    mask_cues(cues, _TEST_WORDLIST, keep_ratio=0.4)

    assert cues[0]["text"] == "бля"
    assert cues[0]["words"][0]["word"] == "бля"


def test_mask_cues_empty_wordlist_returns_unchanged():
    cues = [{"text": "бля fuck", "start": 0.0, "end": 1.0}]

    masked = mask_cues(cues, {"ru": [], "en": []}, keep_ratio=0.4)

    assert masked[0]["text"] == "бля fuck"


def test_cli_risk_rules_works_when_run_as_a_script(tmp_path):
    """`python scripts/profanity.py ... --risk-rules ...` is how SKILL.md step 5
    invokes this, and running a file directly puts scripts/ on sys.path rather
    than the repo root - so the sibling import used to raise ModuleNotFoundError
    for every real call while passing here, because pytest sets pythonpath=["."].
    """
    words = tmp_path / "clip_words.json"
    words.write_text(
        json.dumps([{"word": w, "start": index * 0.5, "end": index * 0.5 + 0.3}
                    for index, w in enumerate((" надо", " было", " член", " ломать"))]),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parent.parent

    # The child writes Cyrillic to stderr; without this it encodes to the
    # Windows console codepage and decoding it as UTF-8 here blows up.
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "scripts/profanity.py", str(words),
         "--wordlist", "data/profanity_wordlist.yaml",
         "--risk-rules", "data/monetization_rules.yaml"],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8", env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[0]), "the risky phrase should produce a span"
    assert "[risk]" in result.stderr
    assert "**" in words.read_text(encoding="utf-8"), "matched words are starred in place"
