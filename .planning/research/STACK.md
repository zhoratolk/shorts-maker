# Stack Research

**Domain:** New capabilities for an existing local Python video-shorts pipeline — platform publishing APIs, monetization-risk detection, LLM title/tag generation, and motion/audio-driven transition selection
**Researched:** 2026-07-07
**Confidence:** MEDIUM-HIGH (official platform docs are HIGH confidence; monetization-risk heuristics and 2026-specific quota numbers are MEDIUM — platforms change these without notice)

This document covers ONLY the four NEW capability areas from PROJECT.md's Active requirements. It does not re-cover faster-whisper/moviepy/ffmpeg core editing, which is already validated in `.planning/codebase/STACK.md`.

## Recommended Stack

### Core Technologies — Feature 1: Platform Publishing APIs

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `google-api-python-client` | already in use (`>=2.100`) | YouTube video upload via `videos.insert` (resumable) | Already a dependency for `youtube_analytics.py` — reuse the same OAuth client, just add the `youtube.upload` scope. Official SDK, well-maintained. |
| `google-auth-oauthlib` | already in use (`>=1.2`) | OAuth flow for upload scope | Same pattern as existing analytics auth — one more scope, one more consent screen. |
| TikTok Content Posting API (`v2/post/publish/video/init/`) — direct REST, no official Python SDK | v2 | Direct-post upload to TikTok | This is the ONLY sanctioned programmatic posting path. Direct Post requires app audit by TikTok before `video.publish` scope is unsandboxed. No paid tier/no per-call fee, but requires business verification. Use `requests` directly — no official Python SDK exists, and none is needed for 2-3 REST calls (init → chunk upload → status poll). |
| Instagram/Meta Graph API (`/{ig-user-id}/media` + `/media_publish`) — direct REST via `requests` | Graph API v22+ | Reels publishing | Requires Instagram **Business/Creator account linked to a Facebook Page**, a Meta Developer App, `instagram_content_publish` permission, and Meta App Review for production (sandboxed to 25 test users otherwise). Video must be reachable at a public `video_url` (container-based upload) — this pipeline will need to stage the rendered clip somewhere Meta's servers can fetch it (see Alternatives). |
| `requests` | already available in Python stdlib-adjacent ecosystem | HTTP calls for TikTok + Instagram REST endpoints | No SDK maturity/trust benefit to any third-party TikTok/Instagram Python wrapper — see "What NOT to Use." |

### Core Technologies — Feature 2: Monetization-Risk Detection

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `pyacoustid` + `chromaprint` (fpcalc binary) | pyacoustid `>=1.3` | Local audio fingerprinting to flag likely-licensed music under game commentary/background music | AcoustID/Chromaprint is the most mature open, actively-maintained fingerprinting stack with a free lookup API (acoustid.org) and a local `fpcalc` binary for fingerprint generation — no per-request cost for fingerprint generation itself, only for the optional cloud lookup. Detects "this contains a known commercial track" which is the #1 driver of YouTube Content ID claims and cross-platform copyright strikes for gaming videos with background music. |
| Rule-based text/keyword classifier (custom, no library needed) | n/a | Flag gambling/hate-speech/hype-speech keywords in transcript before upload | TikTok/YouTube/Instagram do not expose a public "will this get flagged" API — there is no official pre-screening endpoint on any platform. The realistic, honest approach is a local keyword/phrase heuristic (loot box, casino, slot references, slurs list, etc.) run against the Whisper transcript already produced by this pipeline, tuned per platform's public community guidelines. This is advisory, not a guarantee — flag for manual review, never auto-block. |
| YouTube Data API `videos.list(part="status")` post-upload check | already-integrated API | Confirm actual monetization/claim status AFTER upload | The only ground-truth signal is checking `monetizationDetails`/`madeForKids`/content-ID claim status via the API after the video is live — this closes the loop and lets the pipeline learn (e.g., flag a track that got claimed so future clips avoid it). |

### Core Technologies — Feature 3: LLM Title/Tag Generation

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Anthropic Claude API (`anthropic` Python SDK), model `claude-haiku-4-5` | SDK `>=0.40` (check latest), model `claude-haiku-4-5` | Generate title + tag candidates from transcript + channel-style examples | This project is ALREADY orchestrated through Claude Code — adding a direct Anthropic API call for this one task is a natural fit, not a new vendor relationship. Haiku 4.5 at ~$1/$5 per MTok input/output is cheap enough that even generating 10 title variants per clip costs fractions of a cent; a transcript + 5-10 example past titles fits comfortably in a single non-cached call. Structured output (JSON mode / tool-use) makes parsing titles+tags reliable. |
| Local LLM via `ollama` + a small instruct model (e.g. Llama 3.3 8B-class or Qwen3 8B, quantized) | Ollama latest, model TBD by hardware | Fallback/offline title-tag generation matching the "fully on-device" constraint | Given PROJECT.md's explicit constraint that new phases "should not require a permanent cloud backend," offering a local-model path preserves the option to run with zero network dependency, matching the existing fail-open philosophy (like diarization). Quality for short-form title/tag generation (a summarization-adjacent task) is "good enough" on 7-8B class models per 2026 benchmarks — this is not a frontier-reasoning task. |

### Core Technologies — Feature 4: Scene/Motion/Audio Transition Selection

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `scenedetect` (PySceneDetect) | `>=0.6.4` | Detect hard cuts / content discontinuity at clip boundary region, quantify visual "distance" between end-of-A and start-of-B frames | Purpose-built, actively maintained (OpenCV-backed) Python library specifically for this exact job: measuring frame-to-frame content difference to decide "is this a hard cut (favor whip-pan/glitch) or a soft continuation (favor crossfade)." `ContentDetector`'s per-frame HSV difference score can be reused directly as a transition-selection signal even without full scene splitting. |
| `opencv-python` (`cv2`) | already a transitive dependency via pyannote/scenedetect | Optical flow (`cv2.calcOpticalFlowFarneback` for dense flow) to measure motion magnitude/direction at clip boundary — informs match-cut vs whip-pan choice | Dense optical flow gives a per-boundary motion-vector magnitude and dominant direction; a large uniform horizontal vector = camera pan (favor whip-pan transition), near-zero motion = static scene (favor crossfade/match-cut), chaotic/high-variance vectors = favor glitch. This is the standard, well-documented approach — no specialized "transition-recommendation" library exists, so composing scenedetect (shot boundary) + optical flow (motion direction/magnitude) + librosa (audio energy) is the correct level of abstraction. |
| `librosa` | `>=0.10` | Audio energy/onset/beat analysis at clip boundary to sync transition timing and pick audio-driven transitions (e.g., cut on a beat, glitch on a spike) | Already the standard Python audio-analysis library (used broadly in this space); `onset_strength`/`onset_detect` finds transient bursts near the boundary (good glitch/hard-cut timing anchors), RMS energy delta between end-of-A and start-of-B indicates loud→quiet or quiet→loud (informs fade vs cut), and `beat_track` can align cuts to music tempo if background music is present. |
| `ffmpeg` `xfade` filter (already a dependency, no new install) | ffmpeg's built-in filter, already on PATH | Actually render the chosen transition | `xfade` ships ~44 built-in transition types covering everything needed: `fade`/`dissolve` (crossfade), `wipeleft`/`wiperight`/`radial` (wipe/mask family), `smoothleft`/`distance`/`pixelize` (glitch-adjacent — see note below), `hblur` (whip-pan-adjacent blur wipe). No "glitch" or true "whip pan" preset exists natively — those need either a short custom filter chain (`hblur` + directional `wipe` for whip-pan; `pixelize`/RGB-channel-shift filtergraph for glitch) or a pre-rendered overlay asset blended in. This is a render step, not a new stack decision — reuse the existing ffmpeg dependency. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `apscheduler` | `>=3.10` | In-process cron-like scheduling for sequential-numbered auto-publish | Only if the pipeline needs to stay resident and self-schedule; given this is a per-invocation CLI tool today, prefer OS-level scheduling (Windows Task Scheduler) invoking the script, with APScheduler only if a persistent "queue + schedule" daemon becomes necessary. See Architecture note below. |
| `pyacoustid` | `>=1.3` | Chromaprint fingerprint + optional AcoustID cloud lookup | Feature 2 only, and only if network lookup is acceptable — fingerprint generation itself (`fpcalc`) is local/offline; the *lookup* against AcoustID's database requires network. Fail-open if unavailable, matching existing pattern. |
| `anthropic` | latest (`>=0.40`) | Claude API Python SDK | Feature 3, cloud path |
| `ollama` (Python client) | latest | Talk to local Ollama daemon | Feature 3, local path |
| `scenedetect` | `>=0.6.4` | Shot boundary / content-difference scoring | Feature 4 |
| `opencv-python` | `>=4.9` (pin to match whatever pyannote/torch already resolves, avoid conflicting builds) | Optical flow | Feature 4 |
| `librosa` | `>=0.10` | Audio boundary analysis | Feature 4 |
| `soundfile` | `>=0.12` | Fast WAV I/O for librosa (avoids audioread/ffmpeg subprocess overhead per-call) | Feature 4, paired with librosa |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Google Cloud Console project (existing, reuse) | Add `youtube.upload` scope to the already-registered OAuth client | No new project needed — same `client_secret.json` client can request additional scopes; user will need to re-consent once. |
| TikTok Developer Portal app registration | Register app, request Content Posting API + `video.publish` scope, submit for audit | This is the single biggest lead-time risk in Feature 1 — TikTok's app audit for unaudited-scope removal can take days to weeks. Flag this as a phase-blocking dependency to start EARLY, independent of code work. |
| Meta Developer App + Instagram Business account linkage | Register app, request `instagram_content_publish`, submit App Review | Same lead-time risk as TikTok — App Review is not instant. Also requires the Instagram account to already be Business/Creator + linked to a Facebook Page, which is an account-setup prerequisite, not just an API credential. |
| `fpcalc` (Chromaprint CLI binary) | Generates acoustic fingerprints for `pyacoustid` | Separate binary install (like ffmpeg), not a pip package — add to `scripts/setup.py`'s dependency-check pattern. |

## Installation

```bash
# Feature 1 — publishing (YouTube reuses existing google-api-python-client; add scope only)
pip install requests  # TikTok + Instagram REST calls, likely already present transitively

# Feature 2 — monetization-risk detection
pip install pyacoustid
# + install fpcalc binary (chromaprint) separately, e.g. via winget/choco on Windows

# Feature 3 — LLM title/tag generation
pip install anthropic
pip install ollama   # only if local-model path is implemented

# Feature 4 — transition selection
pip install scenedetect[opencv] librosa soundfile
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Official TikTok Content Posting API (direct REST) | `TikTok-Api` (davidteather) or similar unofficial wrapper | Never for publishing — unofficial wrappers are scraping/read-only clients and explicitly cannot post content on a user's behalf; they also violate TikTok ToS and break on any anti-bot change. |
| Official Instagram Graph API | `instagrapi` (private-API wrapper) | Only ever consider `instagrapi` for prototyping/testing against a throwaway account — it uses reverse-engineered private mobile endpoints, is fragile against Meta's account-trust/challenge systems, and risks account bans for the user's real channel. Not acceptable for a production auto-publish feature per PROJECT.md's "irreversibility of auto-publish" constraint. |
| Anthropic Claude Haiku (cloud) for title/tag gen | Local Ollama model | Use local when: user is offline, wants zero marginal cost at high clip volume, or wants to keep 100% of the pipeline device-local per the existing philosophy. Use cloud when: user wants best-in-class hook/title quality (title-writing benefits more from frontier reasoning about virality/humor than raw summarization) and accepts the trivial per-clip cost. Recommend cloud as default (quality), local as configurable fallback (matches fail-open + on-device precedent already set by diarization). |
| `pyacoustid`/Chromaprint for music-fingerprint detection | Training a custom audio-classification model | Never for this project — massively over-engineered for a single-channel local tool; Chromaprint's database-matching approach is the industry-standard technique Content ID itself is modeled on. |
| `scenedetect` + `opencv` optical flow + `librosa` composed together | A single all-in-one "video understanding" ML model (e.g. video-LLM scene classifier) | Consider a video-LLM only if simple heuristic composition proves insufficient in practice after Feature 4 ships — that's a much heavier dependency (large model, likely cloud, higher latency) for what is fundamentally a signal-processing problem today. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Unofficial TikTok/Instagram posting wrappers (`instagrapi` for posting, any TikTok scraping lib for uploads) | ToS violation, account-ban risk, and breaks silently on platform changes — directly conflicts with PROJECT.md's stated concern about auto-publish being "hard to undo" (a banned channel is far worse than a failed API call) | Official Content Posting API (TikTok) / Graph API (Instagram), accept the app-review lead time as a project cost |
| Building a "will this get demonetized" classifier that claims certainty | No platform publishes their actual detection model; any local heuristic is necessarily incomplete and will have false negatives that could mislead the user into false confidence | Frame all Feature 2 output as advisory risk flags for human review, never as a pass/fail gate; always keep a manual override |
| Third-party audio fingerprinting SaaS (e.g., paid Content-ID-clone APIs) for a single-user local tool | Adds a paid cloud dependency and ongoing cost for a hobby-scale, single-channel pipeline — conflicts with the "no permanent cloud backend" constraint | `pyacoustid`/Chromaprint locally, with the free AcoustID lookup as opt-in enhancement, not a requirement |
| Cloud video-understanding APIs (e.g., a hosted "scene analysis" API) for Feature 4 | Adds network dependency + per-call cost + latency to a feature whose signal (frame diff, optical flow, audio energy) is cheap to compute locally in milliseconds | `scenedetect` + `opencv` + `librosa`, all local, all already-adjacent to existing dependencies |
| A generic Python "social-media-scheduler" package (e.g. `social-post-api`, Buffer-clone libraries) | These wrap multiple platforms behind a lowest-common-denominator interface, usually poorly maintained, and hide the platform-specific nuance (container polling for IG, direct-post scopes for TikTok) that this pipeline actually needs to handle correctly | Direct integration against each platform's official SDK/REST API, one small adapter module per platform |

## Stack Patterns by Variant

**If TikTok/Instagram app review is not yet approved when Feature 1 phase starts:**
- Build the upload/publish code path fully, but gate it behind a `dry_run` config flag (per PROJECT.md's explicit requirement for auto-publish safety mechanisms)
- Let YouTube (no equivalent app-review gate for read/write scopes on an already-verified OAuth client, just scope consent) ship first and independently

**If the user wants zero cloud dependency for Feature 3:**
- Default `llm.provider: local` in config, pointing at Ollama; require explicit opt-in `llm.provider: anthropic` + API key to use cloud
- Follow the existing `HF_TOKEN`-style env var pattern for the Anthropic key (never commit it, gitignored, read via `os.environ`)

**If GPU is unavailable (CPU-only machine) for Feature 4's optical flow:**
- `cv2.calcOpticalFlowFarneback` (dense) is CPU-friendly but O(pixels); downsample frames before flow computation (e.g., to 480p) since only boundary-region motion *character* (direction/magnitude class), not pixel-perfect precision, is needed for transition selection

**If a clip boundary has no strong signal either way (ambiguous cut):**
- Default to `crossfade` (safest, most universally acceptable transition) rather than forcing a match-cut/whip-pan/glitch choice from a low-confidence signal

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `scenedetect[opencv]` | `opencv-python>=4.6` | Installing the `[opencv]` extra pulls a compatible OpenCV build; watch for conflicts if `torch`/`pyannote.audio` already pinned a specific OpenCV-adjacent CUDA stack — test in the existing `.venv` before pinning versions in `requirements.txt` |
| `librosa>=0.10` | `numpy`, `scipy` (already transitive via faster-whisper/torch) | No known conflicts; librosa's own numpy floor is well below what faster-whisper/torch already requires |
| `pyacoustid` | Chromaprint `fpcalc` binary must match architecture (win64) | Not a pip-resolvable dependency — must be added to `scripts/setup.py`'s external-binary install pattern, same as ffmpeg |
| `google-api-python-client` (existing) | Add `youtube.upload` scope to same OAuth client used by `youtube_analytics.py` | No version bump needed — this is a scope/consent change, not a library upgrade |
| `anthropic` SDK | Independent of existing stack, no conflicts | New, isolated dependency |

## Sources

- [TikTok Content Posting API Reference — Direct Post](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post) — HIGH confidence, official docs
- [TikTok API Rate Limits 2026](https://www.getphyllo.com/post/tiktok-api-rate-limits-in-2026-quotas-errors-workarounds) — MEDIUM confidence, third-party aggregation of TikTok's published + observed limits
- [Meta: Publish Content using the Instagram Platform](https://developers.facebook.com/docs/instagram-platform/content-publishing/) — HIGH confidence, official docs
- [Instagram Reels API Publishing Guide 2026](https://postproxy.dev/blog/instagram-reels-api-publishing-guide/) — MEDIUM confidence, third-party guide corroborating official flow
- [YouTube Data API — Videos: insert](https://developers.google.com/youtube/v3/docs/videos/insert) — HIGH confidence, official docs
- [YouTube Data API 2026: Quotas, Costs & Real Limits](https://www.socialcrawl.dev/blog/youtube-data-api-2026) — MEDIUM confidence; flags a Dec 2025 quota-cost reduction (1600→100 units) AND a May 2026 undocumented hidden-quota/429 issue — treat actual daily upload throughput as unverified until tested against the real account
- [googleapis/google-api-python-client issue #2753 — hidden upload quota 429s](https://github.com/googleapis/google-api-python-client/issues/2753) — HIGH confidence (primary source, live GitHub issue), confirms real-world quota surprises beyond documented limits
- [PySceneDetect official docs](https://www.scenedetect.com/) and [GitHub repo](https://github.com/Breakthrough/PySceneDetect) — HIGH confidence, official project docs
- [OpenCV optical flow tutorial](https://opencv24-python-tutorials.readthedocs.io/en/latest/py_tutorials/py_video/py_lucas_kanade/py_lucas_kanade.html) — HIGH confidence, official-adjacent OpenCV docs
- [librosa official docs — onset_detect, beat_track](https://librosa.org/doc/main/generated/librosa.onset.onset_detect.html) — HIGH confidence, official docs
- [FFmpeg xfade filter documentation](https://ayosec.github.io/ffmpeg-filters-docs/7.1/Filters/Video/xfade.html) — HIGH confidence, official FFmpeg filter reference
- [Claude API Pricing — Platform Docs](https://platform.claude.com/docs/en/about-claude/pricing) — HIGH confidence, official Anthropic pricing
- [YouTube Content ID — how it works](https://support.google.com/youtube/answer/2797370?hl=en) — HIGH confidence, official YouTube Help
- [TikTok Community Guidelines — Regulated Goods/Gambling](https://www.tiktok.com/community-guidelines/en/regulated-commercial-activities) — HIGH confidence, official policy
- [instagrapi GitHub](https://github.com/subzeroid/instagrapi) and [TikTok-Api GitHub](https://github.com/davidteather/TikTok-Api) — HIGH confidence for capability claims (primary source READMEs), used here only to justify the "what not to use" recommendation
- [Local LLM vs Cloud API 2026 cost breakdown](https://fungies.io/local-llm-vs-cloud-cost-2026/) — LOW-MEDIUM confidence, directional cost/quality framing only, not authoritative benchmarks

---
*Stack research for: shorts-maker new capabilities (publishing, monetization-risk, LLM titles, dynamic transitions)*
*Researched: 2026-07-07*
