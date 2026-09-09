"""The parts of the vision prototype that are decided by code, not by a model."""

from experiments.watch_window import parse_verdict, token_estimate


def test_token_estimate_uses_the_real_frame_shape():
    # 448x252 is what `scale='min(448,iw)':-2` actually produces from 16:9 footage:
    # the filter constrains the width only. 16 x 9 = 144 tokens per frame.
    assert token_estimate(1, 448, 252) == 144
    assert token_estimate(40, 448, 252) == 5760


def test_token_estimate_does_not_assume_a_square():
    # Estimating from the requested side would say 256 per frame - 1.8x too much on
    # every window, which is safe to budget with and wrong to plan with.
    assert token_estimate(1, 448, 448) == 256
    assert token_estimate(1, 448, 252) != token_estimate(1, 448, 448)


def test_parse_verdict_reads_a_bare_object():
    assert parse_verdict('{"clipworthy": 4}') == {"clipworthy": 4}


def test_parse_verdict_survives_a_fence_and_prose():
    answer = 'Вот результат:\n```json\n{"clipworthy": 2, "scene": "menu"}\n```\nГотово.'
    assert parse_verdict(answer)["scene"] == "menu"


def test_parse_verdict_takes_the_first_object_when_the_schema_is_echoed():
    # A greedy \{.*\} spans both objects and parses as neither, which reads as the
    # model refusing to answer when the answer was right there.
    answer = '{"clipworthy": 5, "scene": "action"} и ещё раз: {"clipworthy": 0}'
    assert parse_verdict(answer)["clipworthy"] == 5


def test_parse_verdict_skips_a_brace_that_starts_nothing():
    answer = 'не { объект, а вот он: {"clipworthy": 1}'
    assert parse_verdict(answer)["clipworthy"] == 1


def test_parse_verdict_reports_the_answer_when_there_is_no_json():
    result = parse_verdict("не могу разобрать")
    assert "error" in result and "raw" in result
