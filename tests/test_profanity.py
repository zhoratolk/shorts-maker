import re
from pathlib import Path

from scripts.profanity import compile_patterns, load_wordlist, normalize_word

REPO_ROOT = Path(__file__).resolve().parent.parent
WORDLIST_PATH = str(REPO_ROOT / "data" / "profanity_wordlist.yaml")


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
