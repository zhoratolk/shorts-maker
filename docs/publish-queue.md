# Publish Queue (Phase 3: YouTube Scheduled Auto-Publish)

This document tracks the local publish-queue module (`scripts/publish_queue.py`)
and, in particular, empirical confirmations of API behavior that the code
depends on but that documentation alone doesn't fully settle.

## Kill-path verification (Assumption A1)

**Status: NOT YET PERFORMED.**

`03-RESEARCH.md` Assumption A1 flags that the exact API acceptance of a bare
re-send-private update body —

```python
service.videos().update(
    part="status",
    body={"id": video_id, "status": {"privacyStatus": "private"}},
).execute()
```

— to cancel an already-scheduled release (cancel a pending `publishAt`) is
documented-but-not-empirically-confirmed. `PUB-04`'s kill guarantee is
safety-critical: a video believed killed must not go public.

`cancel_scheduled_release()` + `verify_killed()` in `scripts/publish_queue.py`
implement this body and a mandatory post-kill re-fetch (`videos.list(part=
"status")`) that confirms `privacyStatus == "private"` before `kill_item()`
ever marks a manifest entry `KILLED`. This is the code-level safety net
(Pitfall 2), but it has not yet been run against a **real** scheduled video on
a real channel.

### Required live test (human-in-the-loop, once)

This step requires an actual YouTube upload and cannot be safely automated by
an agent — it needs:
- A real OAuth consent flow for `upload_token.json` (opens a browser; this
  token has never been created on this machine yet as of this plan's
  execution — `upload_token.json` does not exist, only the read-only
  `token.json` from `youtube_analytics.py` does).
- A genuine (short) wait for a real `publishAt` timestamp to pass, to observe
  whether the video actually stays private past it.
- A human decision to use a truly throwaway/private test clip on the real
  channel (not a fixture/mock).

**Steps to perform this verification:**

1. Temporarily set `publish.enabled: true` in `config.yaml` (revert after).
2. Enqueue and upload one throwaway test clip via `upload_and_schedule()`,
   with `publishAt` set only a few minutes in the future (e.g. override
   `daily_slots_utc`/`now` for the test, or just let the natural next grid
   slot be close).
3. Confirm the video appears in YouTube Studio as **Private / Scheduled**.
4. Before `publishAt` passes, call `kill_item()` (or directly
   `cancel_scheduled_release()` + `verify_killed()`) against that video's id.
5. Confirm `verify_killed()` returned `True` and the manifest entry is
   `KILLED`.
6. Wait past the original `publishAt` timestamp and re-check the video's
   status (YouTube Studio, or another `videos.list(part="status")` re-fetch).
   Confirm `privacyStatus` is still `"private"` and the video did **not**
   flip public.
7. Record the outcome below. If the video went public anyway, the bare
   re-send-private body is **insufficient** — do not trust the kill path
   live; capture whatever body the API actually required, and open a gap
   before shipping.

### Outcome

_Not yet recorded — pending the live test above. Update this section with:_
- _Confirmed update body used_
- _Whether the video stayed private past its original `publishAt`_
- _Timestamp/date of the test_
- _Any deviation from the bare `{"privacyStatus": "private"}` body that was
  required_

---

*Phase: 03-youtube-scheduled-auto-publish*
*Plan: 03-03*
