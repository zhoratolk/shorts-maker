from pathlib import Path

import pytest

from scripts.monetization_risk import load_rules, score_all_platforms, score_transcript

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
    assert result["last_checked"] == "2026-07-07"


def test_score_all_platforms_returns_one_entry_per_ruleset_platform_key(rules):
    text = "сегодня заходим на казино и делаем ставки на спорт"

    results = score_all_platforms(text, rules)

    assert set(results.keys()) == {"youtube", "tiktok", "instagram"}
    for platform, result in results.items():
        assert result["platform"] == platform
        assert result["last_checked"] == rules["updated"]
