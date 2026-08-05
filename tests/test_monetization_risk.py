import json
import sys
from pathlib import Path

import pytest

from scripts.monetization_risk import (
    extract_text,
    load_rules,
    main,
    score_all_platforms,
    score_transcript,
)

RULES_PATH = str(Path(__file__).resolve().parent.parent / "data" / "monetization_rules.yaml")


@pytest.fixture()
def rules():
    return load_rules(RULES_PATH)


def test_score_transcript_flags_gambling_keyword_on_youtube(rules):
    text = "сегодня заходим на казино и делаем ставки на спорт"

    result = score_transcript(text, "youtube", rules)

    assert result["platform"] == "youtube"
    assert result["risk_level"] in {"none", "low", "medium", "high"}
    assert result["risk_level"] != "none"
    assert result["flags"], "expected at least one matched category"
    assert any("gambling" in flag for flag in result["flags"])
    assert set(result.keys()) >= {
        "platform", "risk_level", "flags", "flagged_spans", "confidence", "last_checked",
    }


def test_score_transcript_same_text_scores_lower_on_platform_without_category(rules):
    # instagram's ruleset has no "gambling" category at all (MONET-04) - the
    # exact same transcript that scores medium/high on youtube must score
    # none/low on instagram.
    text = "сегодня заходим на казино и делаем ставки на спорт"

    youtube_result = score_transcript(text, "youtube", rules)
    instagram_result = score_transcript(text, "instagram", rules)

    severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    assert severity_rank[instagram_result["risk_level"]] < severity_rank[youtube_result["risk_level"]]
    assert not any("gambling" in flag for flag in instagram_result["flags"])


def test_score_transcript_clean_text_returns_none_or_low_never_raises(rules):
    text = "сегодня был отличный забег в игре, ничего особенного не произошло"

    result = score_transcript(text, "youtube", rules)

    assert result["risk_level"] in {"none", "low"}
    assert result["flags"] == []
    assert result["confidence"] is not None
    assert result["last_checked"] is not None


def test_score_transcript_last_checked_matches_ruleset_updated_field_not_today(rules):
    text = "ничего рискованного тут нет"

    result = score_transcript(text, "youtube", rules)

    assert result["last_checked"] == rules["updated"]

    # Pinned against a stamp that can never be "today", so the test proves the
    # date comes from the ruleset rather than the clock - without having to be
    # edited every time the real ruleset is re-checked.
    stale = {"updated": "2020-01-01", "youtube": {}}
    assert score_transcript(text, "youtube", stale)["last_checked"] == "2020-01-01"


def test_score_all_platforms_returns_one_entry_per_ruleset_platform_key(rules):
    text = "сегодня заходим на казино и делаем ставки на спорт"

    results = score_all_platforms(text, rules)

    assert set(results.keys()) == {"youtube", "tiktok", "instagram"}
    for platform, result in results.items():
        assert result["platform"] == platform
        assert result["last_checked"] == rules["updated"]


def test_whitespace_is_collapsed_before_matching():
    """Callers build this text from a Whisper word list, where every token
    carries its own leading space - a naive join doubles them and a multi-word
    keyword would never match."""
    rules = {
        "updated": "2026-08-06",
        "youtube": {"age_restriction": {"keywords": ["член ломать"], "severity": "high"}},
    }

    result = score_transcript(" Надо  было  член  ломать. ", "youtube", rules)

    assert result["risk_level"] == "high"
    assert result["flags"] == ["age_restriction"]


def test_age_restriction_rules_do_not_flag_crew_member_talk():
    """"член экипажа" is ordinary tank-game speech on this channel; the rules
    use phrases precisely so a bare stem can't flag every one of them."""
    rules = load_rules("data/monetization_rules.yaml")

    for phrase in ("два члена экипажа блять", "взял члена экипажа", "выбило члена экипажа"):
        assert score_transcript(phrase, "youtube", rules)["flags"] == [], phrase


def test_age_restriction_rules_flag_the_phrase_that_got_a_clip_restricted():
    rules = load_rules("data/monetization_rules.yaml")

    result = score_transcript("500 пробоя блядь надо было член ломать", "youtube", rules)

    assert result["flags"] == ["age_restriction"]
    assert result["risk_level"] == "high"


def test_extract_text_reads_a_bare_word_list():
    """The per-clip <clip>_words.json is a list, not a dict - it used to fall
    through to scoring the raw JSON source, so nothing ever matched."""
    words = json.dumps([
        {"word": " Надо", "start": 1.0, "end": 1.2},
        {"word": " было", "start": 1.2, "end": 1.4},
        {"word": " член", "start": 1.4, "end": 1.6},
        {"word": " ломать", "start": 1.6, "end": 2.0},
    ])

    assert extract_text(words) == " Надо  было  член  ломать"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (json.dumps({"text": "прямой текст"}), "прямой текст"),
        (json.dumps({"segments": [{"text": "первый"}, {"text": " второй"}]}), "первый  второй"),
        (json.dumps([{"text": "сегмент один"}, {"text": "сегмент два"}]), "сегмент один сегмент два"),
        ("просто текст, не json", "просто текст, не json"),
    ],
)
def test_extract_text_handles_every_shape_the_pipeline_produces(raw, expected):
    assert extract_text(raw) == expected


def test_cli_flags_the_restricted_clip_from_its_words_file(tmp_path, capsys, monkeypatch):
    """End to end through the CLI: this is the call SKILL.md documents, and it
    silently returned 'clean' for every clip before extract_text existed."""
    words = tmp_path / "clip_words.json"
    words.write_text(
        json.dumps([{"word": w, "start": 0.0, "end": 0.1} for w in (" надо", " было", " член", " ломать")]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv",
        ["monetization_risk.py", str(words), "--rules", RULES_PATH, "--platform", "youtube"],
    )

    main()

    printed = capsys.readouterr().out
    # main() prints the JSON result, then the input path on its own last line.
    result = json.loads(printed.rsplit("\n", 2)[0])
    assert result["flags"] == ["age_restriction"]
    assert result["risk_level"] == "high"
