---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 06
current_phase_name: tiktok-instagram-auto-publish
status: executing
stopped_at: Completed 06-01-PLAN.md
last_updated: "2026-07-10T11:44:25.243Z"
last_activity: 2026-07-10
last_activity_desc: Phase 06 execution started
progress:
  total_phases: 7
  completed_phases: 5
  total_plans: 27
  completed_plans: 24
  percent: 71
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-07)

**Core value:** Из сырой записи стрима автоматически получить готовый к публикации вертикальный клип — без ручной нарезки и без потери самых залипательных моментов.
**Current focus:** Phase 06 — tiktok-instagram-auto-publish

## Current Position

Phase: 06 (tiktok-instagram-auto-publish) — EXECUTING
Plan: 5 of 7
Status: Ready to execute
Last activity: 2026-07-10 — Phase 06 execution started

Note: Phase 2 (LLM Title & Tag Generation) has plan 02-02 still pending — Phase 3 planning/execution proceeded per project workflow while 02-02 remains open; see Pending Todos.

Progress: [███░░░░░░░] 17% (1/6 phases)

## Performance Metrics

**Velocity:**

- Total plans completed: 5
- Average duration: 30 min
- Total execution time: 3.7 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3/3 | 100 min | 33 min |
| 02 | 1/2 | 4 min | 4 min |
| 03 | 1/4 | 120 min | 120 min |
| 05 | 5 | - | - |

**Recent Trend:**

- Last 5 plans: 35 min, ~25 min, ~40 min, 4 min, 120 min
- Trend: -

*Updated after each plan completion*
| Phase 02 P02 | 5min | 2 tasks | 2 files |
| Phase 03 P01 | 120min | 3 tasks | 4 files |
| Phase 03 P02 | 1h | 3 tasks | 3 files |
| Phase 03-youtube-scheduled-auto-publish P03 | 35min | 3 tasks | 3 files |
| Phase 03-youtube-scheduled-auto-publish P04 | 40min | 3 tasks | 3 files |
| Phase 04-context-driven-transitions P01 | 30min | 2 tasks | 1 files |
| Phase 04 P02 | 12min | 2 tasks | 5 files |
| Phase 04-context-driven-transitions P03 | 5min | 3 tasks | 3 files |
| Phase 04-context-driven-transitions P04 | 4min | 3 tasks | 2 files |
| Phase 04-context-driven-transitions P05 | 7min | 3 tasks | 2 files |
| Phase 04-context-driven-transitions P06 | 6min | 2 tasks | 2 files |
| Phase 05 P01 | 5min | 2 tasks | 2 files |
| Phase 05-sub-threshold-highlight-compilation P02 | 2min | 2 tasks | 5 files |
| Phase 05-sub-threshold-highlight-compilation P03 | 20min | 2 tasks | 3 files |
| Phase 05-sub-threshold-highlight-compilation P04 | 15min | 2 tasks | 1 files |
| Phase 05 P05 | 15min | 3 tasks | 5 files |
| Phase 06 P01 | 1min | 2 tasks | 1 files |
| Phase 06 P02 | 5min | 2 tasks | 3 files |
| Phase 06 P03 | 25min | 3 tasks | 2 files |
| Phase 06 P04 | 6min | 3 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: Monetization-risk and style-profile merged into one Phase 1 (both independent, both foundational, standard granularity) rather than two separate phases
- Roadmap: Transitions (Phase 4) sequenced before Compilation (Phase 5) since compilation's stitching step consumes the transition engine
- Roadmap: TikTok/Instagram (Phase 6) sequenced last since both carry external app-review/audit gates that should be started early but not block earlier phases
- Roadmap: Profanity Auto-Bleep added as Phase 7, depends on Phase 1's transcript/render pipeline only — independent of Phase 5 (compilation) and Phase 6 (auto-publish), so it doesn't block or get blocked by either
- [Phase 05-01]: append_compilation_sections_markdown takes plain dicts (not Candidate) for both groups and unmatched, per the plan's explicit signature over PATTERNS.md's illustrative Candidate-typed sketch
- [Phase 05-01]: no CLI subcommand added for append_compilation_sections_markdown — SKILL.md (Plan 05-04) will call it via a python -c one-liner, matching style_profile.py precedent
- [Phase 05-sub-threshold-highlight-compilation]: Plan 05-02: capping-below-MIN_GROUP_SIZE error message wording left to implementer discretion (only Guard 1/Guard 2 wording was prescribed word-for-word by the plan)
- [Phase 05-sub-threshold-highlight-compilation]: Plan 05-02: build_compilation_entry takes plain member dicts (not a Candidate-typed object), matching the plan's explicit signature and Plan 05-01's dict-based precedent at this hand-off boundary
- [Phase ?]: [Phase 05-03]: _build_compilation_fold returns only (fold_stages, total_duration) - trim_stages are built once upfront in build_compilation_command (not per-branch) since compilation trims are never extended into a gap, unlike _build_transition_fold's own trim_stages construction
- [Phase ?]: [Phase 05-03]: render_clip's clamp_clip_bounds call moved below the hoisted crop/punch-zoom/subtitles block and only runs in the non-compilation else-branch; each compilation member is clamped individually inside the compilation branch instead
- [Phase ?]: [Phase 05-04]: .claude/ is gitignored project-wide, so both tasks' SKILL.md edits (sub-threshold detection/tagging bullet + step 5b grouping-pass subsection) live on disk only, not in git history - same convention as 02-01/04-06
- [Phase ?]: [Phase 05-04]: The compilation PLAN.json entry (scripts/compilation.py CLI call) is documented as built once at the end of step 5b, after crop_style/punch-zoom/title/subtitles/metadata are all decided - mirrors the single-clip 'write merged results' final-assembly pattern rather than the plan's raw bullet-listing order
- [Phase ?]: [Phase 05-05]: CR-01 fix truncates boundary_transitions to the fitted post-cap prefix inside build_compilation_entry's validation block only, before the existing length-mismatch raise, so a genuinely too-short list still raises unchanged
- [Phase ?]: [Phase 05-05]: WR-01/WR-02 SKILL.md edits are disk-only (not committed) - .claude/ is gitignored project-wide, same pre-existing convention as Plans 02-01/04-06
- [Phase 06]: [Phase 06-01]: requests documented as an unconditional direct dependency (not a feature-flagged optional block), matching the google-api-python-client wording convention, since it is imported unconditionally at module top level by scripts/tiktok_publish.py and scripts/instagram_publish.py in later plans
- [Phase 06]: [Phase 06-01]: Legitimacy checkpoint for requests resolved via live pypi.org verification performed by the orchestrating session (github.com/psf/requests confirmed, no typosquat, version 2.34.2 matches current stable release) rather than a literal interactive human reply - documented as the audit trail per T-06-SC
- [Phase 06-02]: Extended flat PublishConfig in place with tiktok_*/instagram_* fields rather than sibling TikTokPublishConfig/InstagramPublishConfig dataclasses, per D-01 per-platform enable-flag wording
- [Phase 06-02]: No new _validate() rule added for the 8 new PublishConfig fields (bool/path fields need no extra validation), matching MonetizationConfig precedent
- [Phase ?]: [Phase 06-03]: kill_item and the CLI wrapper are deliberately out of scope for this plan (deferred to 06-05) - only pause_item/resume_item are implemented, matching the must_haves artifact list
- [Phase ?]: [Phase 06-03]: video_share_url populated from status/fetch's publicaly_available_post_id on both the direct-success and reconcile-adopts-PUBLISH_COMPLETE paths
- [Phase ?]: [Phase 06-04]: load_credentials refresh trigger simplified to a single 24h-age threshold rather than RESEARCH.md's fuller age+days-remaining wording - Instagram's actual hard API requirement is only the 24h minimum age
- [Phase ?]: [Phase 06-04]: _check_meta_permission_error checks status_code==403 OR permission-flavored substrings in message/type/code; any other non-2xx propagates as plain requests.HTTPError - documented best-effort per 06-RESEARCH.md's no-live-call caveat
- [Phase ?]: [Phase 06-04]: no-pre-publish-gating-call verification tests assert against instagram_publish's module namespace rather than raw source-text grep, avoiding false positives from explanatory docstring prose

### Roadmap Evolution

- Phase 7 added: Profanity Auto-Bleep — detect swear words in the Whisper transcript, mask with a quiet overlay tone (audio keeps flowing, not full silence) so platform speech-to-text moderation/demonetization scanners can't pick them up
- Plan 01-01: data/monetization_rules.yaml is committed (not gitignored) — generic platform-policy data, zero channel-specific content
- Plan 01-01: last_checked on every risk flag is copied verbatim from the ruleset's own `updated:` date stamp, not today's date, so staleness is visible (PITFALLS.md Pitfall 2)
- Plan 01-01: risk dict is an additive optional field on metadata.py's platform fields — never a gate, output byte-identical when absent
- Plan 01-03: style_profile.py is a pure transform over youtube_analytics.py's cache — no parallel OAuth flow; output written only to gitignored work/_profile/, verified via an automated privacy-guard test (path-under-work/ + git check-ignore)
- Plan 01-03: performance signal prefers average_view_percentage, falls back to view_count when Analytics API retention data is unavailable
- Plan 01-02: audio-fingerprint copyright flag merges into Plan 01's exact risk-dict shape via a pure merge_audio_flag function, reusing its severity ordering — no second risk-dict schema
- Plan 01-02: audio fingerprinting is opt-in (audio_fingerprint_enabled: false default) since it needs the external fpcalc/Chromaprint binary; AcoustID network lookup is a further opt-in layer on top (enable_lookup)
- Plan 02-01: added a small pure Python helper (format_naming_examples_block) rather than a SKILL.md-only Read+format instruction — unit-testable, zero new imports, matches D-01's intent (excludes only a new API-calling script)
- Plan 02-01: few-shot voice-grounding instruction placed immediately before the existing 'load docs/metadata-writing-ru.md' sentence in SKILL.md step 5 — prominent placement per Pitfall 5 (buried/passive framing risks generic output)
- Plan 02-01: `.claude/` is gitignored project-wide, so the SKILL.md edit lives on disk only, not in git history — this is a pre-existing repo convention, not a regression (see 02-01-SUMMARY.md Deviations)
- [Phase 02]: Plan 02-02: REQUIREMENTS.md Traceability table TAGS-01/TAGS-02 rows reworded from bare Pending to deliberate reframed/deferred phrasing citing 02-CONTEXT.md D-01/D-02/D-03
- [Phase 02]: Plan 02-02: ROADMAP.md Phase 2 detail block gained a reconciliation note aligning literal Success Criteria 1/2 wording with the orchestrator-session architecture (TAGS-01) and Phase 6 deferral (TAGS-02)
- [Phase 03]: Plan 03-01: enqueue() reads title/description/tags verbatim from already-finished per-clip metadata (D-01/D-02) — no metadata regeneration logic in this plan
- [Phase 03]: Plan 03-01: daily_slots_utc default set to ["09:00","15:00","20:00"] (Claude's discretion per D-07), aligned with the ~3h periodic-check cadence for later plans to consume
- [Phase 03]: Plan 03-01: publish.enabled hard-defaults to False both on the dataclass and when the `publish:` config section is entirely absent — PUB-03 dry-run guarantee at the config layer
- [Phase 03]: Plan 03-02: Seq marker for reconciliation embedded as trailing [queue-id: N] line in description (no dedicated custom-metadata field on videos.insert)
- [Phase 03]: Plan 03-02: Field-limit validation lives in build_insert_body (raises ValueError), keeping the pure body-builder independently testable
- [Phase ?]: kill_item treats UPLOADING-with-no-video_id as not-yet-uploaded (local-only KILLED flip), same as QUEUED/PAUSED — An in-flight upload that hasn't produced a video_id yet has nothing on YouTube to revert
- [Phase 03-03]: reconcile_uploading fetches descriptions via a dedicated videos.list(part=snippet) call rather than modifying youtube_analytics.py's list_uploaded_videos — Keeps youtube_analytics.py read-only-reuse scope untouched; that helper's playlistItems response doesn't carry description
- [Phase 03-03]: reconcile_all_uploading skips an UPLOADING entry that already has a video_id recorded — That is not the stuck-mid-upload-no-record case PUB-05 targets; touching it risks clobbering a legitimate in-progress multi-chunk upload
- [Phase 03-youtube-scheduled-auto-publish]: Notification-log marker is a persisted line-count in a sibling .read file, not a byte offset — Simpler to reason about with splitlines, no multi-byte UTF-8 boundary risk; log is always read in full and re-diffed, never seeked into
- [Phase 03-youtube-scheduled-auto-publish]: check and now both call one shared upload_one helper wrapping upload_and_schedule — Structurally guarantees the two trigger paths can never diverge onto separate publish logic (D-05)
- [Phase 04-01]: Human approved opencv-python-headless + librosa after pypi.org legitimacy review (T-04-SC mitigated); pip install pulled numpy 2.5.0 -> 2.4.6 transitively via numba, verified pip check clean
- [Phase 04-02]: TransitionsConfig min_overlap_seconds > transition_duration is a hard ConfigError (a floor above the whole window is nonsensical), mirroring jumpcuts' cut_threshold_seconds >= detect_min_seconds precedent
- [Phase 04-02]: compute_boundary_gaps has no standalone CLI subcommand - internal helper only for render.py/transitions.py, matching total_kept_duration precedent
- [Phase 04-03]: Motion-test fixtures use a shifted white-square-on-black frame pair (real optical-flow displacement) rather than differently-colored solid frames, since Farneback flow has no texture/gradient to correlate on uniform color blocks - solid-color pairs reserved for the similarity/histogram test instead
- [Phase 04-03]: Fail-open tests for cv2/librosa use a deterministic builtins.__import__ monkeypatch rather than relying on the dependency actually being absent from the venv, since both are already installed (04-01)
- [Phase 04-04]: classify_transition's moderate-motion band (motion_threshold/2 <= motion < motion_threshold) makes crossfade/whip_pan/glitch/mask_wipe mutually exclusive and independently reachable, resolving an overlap in 04-RESEARCH.md's suggested mapping
- [Phase 04-04]: select_boundary_transitions imports scripts.frames.extract_frames and scripts.jumpcuts.compute_boundary_gaps at module top level - first cross-script import in this codebase, safe since both source modules are stdlib-only
- [Phase 04-04]: config_fields is a plain dict of the 4 tunable knobs, not a TransitionsConfig instance - scripts/*.py never imports scripts/config.py at runtime (project Anti-Pattern); CLI subcommand duplicates TransitionsConfig defaults as module constants
- [Phase ?]: [Phase 04-05]: VALID_TRANSITIONS in render.py is a duplicated frozenset (not imported from scripts.transitions.TRANSITION_TYPES), drift-guarded by a dedicated test, so render.py stays runnable as a standalone CLI without a sys.path insert
- [Phase ?]: [Phase 04-05]: build_jumpcut_command's hybrid branch runs the exact pre-existing flat-concat code path when boundary_transitions is None or every entry is cut/match_cut, verified byte-identical via explicit equality tests against the omitted-param case, not just relied on by construction
- [Phase ?]: [Phase 04-05]: xfade overlap duration is clamp(min(transition_duration, gap), min_overlap_seconds, transition_duration), split symmetrically into the two adjacent segments' trims - always <= the boundary's own pause gap, so a transition never eats real kept content
- [Phase 04-06]: .claude/ is gitignored project-wide, so the SKILL.md orchestration-step edit lives on disk only, not in git history - same pre-existing convention as 02-01, not a regression
- [Phase 04-06]: Integration test forces boundary_transitions directly on the plan_entry rather than calling select_boundary_transitions, isolating the render-layer xfade fold path from cv2/librosa so the test stays skippable purely on ffmpeg presence

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 6 (TikTok/Instagram): external app-audit/review lead times are days-to-weeks and outside developer control — start the audit application early (in parallel with Phase 1), per research SUMMARY.md
- Phase 6 (TikTok): unaudited clients are restricted to SELF_ONLY (private) uploads; upload calls return success even when nothing is actually public — needs a post-publish visibility-verification check
- OAuth credentials for 3 platforms raise the stakes of this project's prior real leaked-data incident — credential storage location/discipline must be finalized before Phase 3/6 upload code is written
- Environment quirk (not a code bug): default pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine, breaking plain `pytest -x` runs that rely on `tmp_path`; verified with `--basetemp` override during Plan 03-01. Unrelated to any code change — informational for future sessions.
- 03-03 Task 3 (Assumption A1 kill-body live verification) is an outstanding human-check: requires OAuth consent for upload_token.json (does not exist yet), a real throwaway private test upload, and waiting past a real publishAt to confirm the kill actually cancels the scheduled release. See docs/publish-queue.md 'Kill-path verification' section and 03-03-SUMMARY.md Checkpoint section for exact steps. Do not trust kill_item live until this is performed.
- 04-01 Task 1: blocking-human legitimacy checkpoint for opencv-python-headless + librosa pending human approval before pip install (Task 2) can run — see 04-01-SUMMARY.md

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260708-4h4 | Add -loglevel error to ffmpeg commands in render.py to suppress noisy failure output | 2026-07-08 | e0739cf | [260708-4h4-add-loglevel-error-to-ffmpeg-commands-in](./quick/260708-4h4-add-loglevel-error-to-ffmpeg-commands-in/) |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-07-10T11:43:29.978Z
Stopped at: Completed 06-01-PLAN.md
Resume file: None
