"""Tests for the batch enqueue step.

Every field this step fills used to be an optional argument on enqueue() that a
throwaway script had to remember. These tests pin the ones whose absence is
silent: the poster, the moment tag, the duration, and the publish order.
"""

from __future__ import annotations

import json
import sys

import pytest

from scripts.config import Config
from scripts.enqueue_batch import (
    EnqueueBatchError,
    batch_order,
    clip_duration,
    enqueue_batch,
    load_youtube_metadata,
)
from scripts.publish_queue import load_queue


def make_config(tmp_path) -> Config:
    config = Config(input_dir="in", output_dir=str(tmp_path / "out"))
    config.publish.queue_path = str(tmp_path / "queue.json")
    return config


def write_batch(tmp_path, entries, *, render=True, poster=True):
    """Lays out a rendered batch the way the pipeline leaves it."""
    work = tmp_path / "work"
    (work / "metadata_data").mkdir(parents=True)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)

    for entry in entries:
        stem = entry["output_filename"][:-4]
        (work / "metadata_data" / f"{stem}.json").write_text(
            json.dumps({"youtube": {
                "title": f"Title {stem}",
                "description": f"Desc {stem}",
                "tags": ["a", "b"],
            }}, ensure_ascii=False),
            encoding="utf-8",
        )
        if render:
            (out / entry["output_filename"]).write_bytes(b"")
            (out / f"{stem}.txt").write_text("meta", encoding="utf-8")
        if render and poster:
            (out / f"{stem}.thumb.png").write_bytes(b"")

    plan = work / "PLAN.json"
    plan.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return str(plan), str(out)


def entry(name, **overrides):
    base = {"output_filename": f"{name}.mp4", "start": 100.0, "end": 130.0, "moment_tag": "тильт"}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "plan_entry,expected",
    [
        ({"start": 10.0, "end": 40.0}, 30.0),
        ({"start": 10.0, "end": 40.0, "keep_segments": [[10.0, 20.0], [25.0, 40.0]]}, 25.0),
        ({"start": 0.0, "end": 0.0, "segments": [[0.0, 12.0], [50.0, 61.5]]}, 23.5),
        (
            {
                "type": "compilation",
                "segments": [
                    {"start": 0.0, "end": 12.0},
                    {"start": 50.0, "end": 61.5},
                ],
            },
            23.5,
        ),
        (
            {
                "type": "compilation",
                "segments": [
                    {"start": 0.0, "end": 12.0, "keep_segments": [[0.0, 5.0], [8.0, 12.0]]},
                    {"start": 50.0, "end": 61.5},
                ],
            },
            20.5,
        ),
    ],
)
def test_clip_duration_covers_jump_cuts_and_compilations(plan_entry, expected):
    """Форма, которую пишет build_compilation_entry, — словари, а не пары.

    На парах тест был зелёным, а продакшен такой формы не создаёт никогда: распаковка
    словаря даёт имена ключей, и float("end") падает. Компиляция — штатный продукт шага
    5b, так что падало в самом конце дорогого рендера, а очередь сохраняется один раз в
    конце — весь батч оставался непоставленным и неопубликованным.
    """
    assert clip_duration(plan_entry) == expected


def test_batch_order_spreads_the_loop_clips():
    entries = [entry(f"r{index}") for index in range(6)] + [
        entry("L0", loop=True), entry("L1", loop=True)
    ]

    ordered = batch_order(entries)

    positions = [i for i, e in enumerate(ordered) if e.get("loop")]
    assert len(ordered) == 8
    assert positions[1] - positions[0] > 1


def test_enqueue_batch_fills_every_field_from_what_the_pipeline_wrote(tmp_path):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a", keep_segments=[[100.0, 118.0]])])

    added = enqueue_batch(config, plan, out)

    assert len(added) == 1
    row = added[0]
    assert row["title"] == "Title clip-a"
    assert row["description"] == "Desc clip-a"
    assert row["tags"] == ["a", "b"]
    assert row["moment_tag"] == "тильт"
    assert row["source_duration"] == 18.0
    assert row["thumbnail_path"].endswith("clip-a.thumb.png")
    assert row["status"] == "queued"


def test_enqueue_batch_persists_the_queue(tmp_path):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a"), entry("clip-b")])

    enqueue_batch(config, plan, out)

    reloaded = load_queue(config.publish.queue_path)
    assert [e["clip_id"] for e in reloaded["entries"]] == ["clip-a", "clip-b"]


def test_enqueue_batch_is_idempotent_across_reruns(tmp_path):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a")])

    first = enqueue_batch(config, plan, out)
    second = enqueue_batch(config, plan, out)

    assert len(first) == 1
    assert second == []  # already queued, not re-added or renumbered
    assert len(load_queue(config.publish.queue_path)["entries"]) == 1


def test_enqueue_batch_skips_a_clip_that_never_rendered(tmp_path, capsys):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a")], render=False)

    assert enqueue_batch(config, plan, out) == []
    assert "rendered clip not found" in capsys.readouterr().err


def test_strict_mode_refuses_a_partial_batch(tmp_path):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a")], render=False)

    with pytest.raises(EnqueueBatchError, match="rendered clip not found"):
        enqueue_batch(config, plan, out, skip_missing=False)


def test_missing_metadata_is_a_hard_error_not_a_blank_title(tmp_path):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a")])
    (tmp_path / "work" / "metadata_data" / "clip-a.json").unlink()

    with pytest.raises(EnqueueBatchError, match="no metadata"):
        enqueue_batch(config, plan, out)


def test_a_batch_without_posters_still_enqueues(tmp_path, capsys):
    config = make_config(tmp_path)
    plan, out = write_batch(tmp_path, [entry("clip-a")], poster=False)

    added = enqueue_batch(config, plan, out)

    assert added[0]["thumbnail_path"] == ""
    assert "БЕЗ ОБЛОЖКИ" in capsys.readouterr().out


def test_load_youtube_metadata_rejects_a_file_without_a_youtube_block(tmp_path):
    plan, _ = write_batch(tmp_path, [entry("clip-a")])
    path = tmp_path / "work" / "metadata_data" / "clip-a.json"
    path.write_text(json.dumps({"tiktok": {}}), encoding="utf-8")

    with pytest.raises(EnqueueBatchError, match="no 'youtube' block"):
        load_youtube_metadata(plan, {"output_filename": "clip-a.mp4"})


class _FakePublish:
    def __init__(self, tmp_path, enabled):
        self.enabled = enabled
        self.queue_path = str(tmp_path / "queue.json")
        self.notifications_path = str(tmp_path / "log.txt")
        self.client_secret_path = "secrets/yt_client.json"
        self.upload_token_path = "secrets/yt_token.json"


class _FakeThumbnail:
    upload = True


def _config(tmp_path, enabled=True):
    class _Config:
        output_dir = str(tmp_path)
        publish = _FakePublish(tmp_path, enabled)
        thumbnail = _FakeThumbnail()
    return _Config()



# --- the CLI's second half: enqueue means upload (2026-08-23) --------------


def test_main_uploads_after_enqueuing(monkeypatch, tmp_path):
    """The regression this guards: --local-only was wired into argparse while
    the upload call itself never made it into main(), so every invocation
    behaved as if --local-only had been passed. Nothing failed - the batch
    simply sat in the queue looking enqueued."""
    import scripts.enqueue_batch as module

    calls = []
    monkeypatch.setattr(module, "enqueue_batch", lambda *a, **k: [])
    monkeypatch.setattr(module, "load_queue", lambda path: {"entries": []})
    monkeypatch.setattr(module, "load_config", lambda path: _config(tmp_path))
    monkeypatch.setattr(module, "upload_queued_batch",
                        lambda config, secret, token: calls.append((secret, token)))
    monkeypatch.setattr(sys, "argv", ["enqueue_batch.py", "PLAN.json"])

    module.main()

    # Пути берутся из конфига, а не из литералов: оба поля объявлены и валидируются в
    # config.py, но не читались — вынести секреты из корня репозитория (разумное решение)
    # означало FileNotFoundError в самом конце многочасового рендера.
    assert calls == [("secrets/yt_client.json", "secrets/yt_token.json")]


def test_main_skips_the_upload_when_told_to_stay_local(monkeypatch, tmp_path):
    import scripts.enqueue_batch as module

    monkeypatch.setattr(module, "enqueue_batch", lambda *a, **k: [])
    monkeypatch.setattr(module, "load_queue", lambda path: {"entries": []})
    monkeypatch.setattr(module, "load_config", lambda path: _config(tmp_path))
    monkeypatch.setattr(module, "upload_queued_batch", lambda *a: (_ for _ in ()).throw(
        AssertionError("--local-only must not upload")))
    monkeypatch.setattr(sys, "argv", ["enqueue_batch.py", "PLAN.json", "--local-only"])

    module.main()


def test_main_uploads_nothing_while_publishing_is_disabled(monkeypatch, tmp_path):
    import scripts.enqueue_batch as module

    monkeypatch.setattr(module, "enqueue_batch", lambda *a, **k: [])
    monkeypatch.setattr(module, "load_queue", lambda path: {"entries": []})
    monkeypatch.setattr(module, "load_config", lambda path: _config(tmp_path, enabled=False))
    monkeypatch.setattr(module, "upload_queued_batch", lambda *a: (_ for _ in ()).throw(
        AssertionError("publish.enabled is false - nothing may upload")))
    monkeypatch.setattr(sys, "argv", ["enqueue_batch.py", "PLAN.json"])

    module.main()


def test_main_lets_the_flags_win_over_the_config(monkeypatch, tmp_path):
    import scripts.enqueue_batch as module

    calls = []
    monkeypatch.setattr(module, "enqueue_batch", lambda *a, **k: [])
    monkeypatch.setattr(module, "load_queue", lambda path: {"entries": []})
    monkeypatch.setattr(module, "load_config", lambda path: _config(tmp_path))
    monkeypatch.setattr(module, "upload_queued_batch",
                        lambda config, secret, token: calls.append((secret, token)))
    monkeypatch.setattr(sys, "argv", [
        "enqueue_batch.py", "PLAN.json", "--client-secret", "a.json", "--token", "b.json",
    ])

    module.main()

    assert calls == [("a.json", "b.json")]
