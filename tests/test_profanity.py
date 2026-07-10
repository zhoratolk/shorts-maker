import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.jumpcuts import remap_words
from scripts.profanity import compile_patterns, find_profane_spans, load_wordlist, normalize_word

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
        {"word": "f0ck", "start": 1.0, "end": 1.3},
        {"word": "чисто", "start": 1.4, "end": 1.7},
    ]

    spans = find_profane_spans(words, _TEST_WORDLIST, pad_seconds=0.0)

    assert spans == [(0.5, 0.9), (1.0, 1.3)]


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
