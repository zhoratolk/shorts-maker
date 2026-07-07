from scripts.monetization_audio import (
    generate_fingerprint,
    merge_audio_flag,
    to_risk_flag,
)


class FakeResult:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


FPCALC_STDOUT = "DURATION=183\nFINGERPRINT=AQAAT0mUaEkSRZEGkJqk4A\n"


def test_generate_fingerprint_parses_fpcalc_output():
    result = generate_fingerprint("clip.wav", runner=lambda *a, **k: FakeResult(FPCALC_STDOUT))

    assert result == {"duration": 183, "fingerprint": "AQAAT0mUaEkSRZEGkJqk4A"}


def test_generate_fingerprint_fails_open_when_binary_missing():
    def fake_runner(*args, **kwargs):
        raise FileNotFoundError()

    result = generate_fingerprint("clip.wav", runner=fake_runner)

    assert result is None


def test_generate_fingerprint_fails_open_on_subprocess_error():
    import subprocess

    def fake_runner(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["fpcalc"])

    result = generate_fingerprint("clip.wav", runner=fake_runner)

    assert result is None


def test_to_risk_flag_positive_match_returns_advisory_flag():
    match = {"category": "copyrighted_audio", "confidence": "medium"}

    flag = to_risk_flag(match, last_checked="2026-06-01")

    assert flag["category"] == "copyrighted_audio"
    assert flag["confidence"] == "medium"
    assert flag["last_checked"] == "2026-06-01"
    assert flag["severity"] in {"low", "medium", "high"}


def test_merge_audio_flag_adds_flag_without_dropping_keyword_flags():
    existing_risk = {
        "platform": "youtube",
        "risk_level": "low",
        "flags": ["gambling"],
        "flagged_spans": [{"start": 0, "end": 5, "reason": "gambling", "matched_text": "slots"}],
        "confidence": "low",
        "last_checked": "2026-06-01",
    }
    audio_flag = {"category": "copyrighted_audio", "confidence": "high", "last_checked": "2026-07-01", "severity": "high"}

    merged = merge_audio_flag(existing_risk, audio_flag)

    assert "gambling" in merged["flags"]
    assert "copyrighted_audio" in merged["flags"]
    assert merged["risk_level"] == "high"


def test_merge_audio_flag_none_returns_risk_dict_unchanged():
    existing_risk = {
        "platform": "youtube",
        "risk_level": "none",
        "flags": [],
        "flagged_spans": [],
        "confidence": "low",
        "last_checked": "2026-06-01",
    }

    merged = merge_audio_flag(existing_risk, None)

    assert merged == existing_risk
