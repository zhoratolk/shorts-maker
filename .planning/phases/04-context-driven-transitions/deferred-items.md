# Deferred Items — Phase 04 (context-driven-transitions)

Out-of-scope discoveries logged during plan execution, per the executor's SCOPE BOUNDARY rule
(only auto-fix issues directly caused by the current task's changes).

## From Plan 04-03

- **Pre-existing failure, unrelated to this plan:** `tests/test_publish_queue.py` has 3 failing
  tests (`test_upload_and_schedule_enabled_drives_status_transitions_and_body`,
  `test_check_enabled_uploads_exactly_one_item_and_appends_one_notification`,
  `test_now_targets_the_named_clip_via_same_upload_path`) — all fail with
  `ModuleNotFoundError: No module named 'googleapiclient'` inside `scripts/publish_queue.py`'s
  deferred import of `googleapiclient.http.MediaFileUpload`. This is a missing optional dependency
  in the project `.venv` (Phase 3's YouTube upload path), not caused by any change in this plan
  (`scripts/transitions.py`, `tests/test_transitions.py`). Confirmed pre-existing by running the
  failing test in isolation and inspecting the traceback — the failure originates entirely inside
  `publish_queue.py`, a file this plan never touched. Not fixed here; out of scope.
