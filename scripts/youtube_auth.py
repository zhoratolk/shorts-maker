"""One OAuth consent, one cached token, for every YouTube call this repo makes.

Split out of youtube_analytics.py on 2026-09-23: the analytics fetcher is an
optional feature that imports `requests` at module scope, while the publish
queue needs the token paths on a plain `--help` run, and pulling the whole
fetcher in for two constants coupled the CLI to it (a test stubbing
scripts.youtube_analytics broke argument parsing). Nothing here imports
anything heavier than the standard library; the Google libraries stay inside
load_credentials, the one place that talks to them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Read-only scopes - the analytics fetcher never uploads/edits/deletes anything.
# yt-analytics.readonly covers both the interactive Analytics API and the bulk
# Reporting API used for thumbnail-impressions data - no separate consent.
DATA_API_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_API_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPES = [DATA_API_SCOPE, ANALYTICS_API_SCOPE]

# The scope publish_queue.py uploads and schedules with (its own UPLOAD_SCOPE
# is the same string; it stays defined there so that module reads standalone).
MANAGE_API_SCOPE = "https://www.googleapis.com/auth/youtube"

# One consent for everything this repo does to YouTube. Three separate token
# files - read-only analytics, upload, and a comments token from a one-off
# script - meant three separate consents against the same OAuth client, and on
# 2026-09-22 the upload one came back `invalid_grant: Token has been expired or
# revoked` ten days after it was issued, with four rendered clips stuck behind
# it. Google evicts refresh tokens per (account, client) pair, so consents that
# exist only to hold a narrower scope are a liability, not a safety measure:
# each one is another token that can push an older one out. `youtube` already
# covers everything `youtube.readonly` can do, so the union is two scopes.
ALL_SCOPES = [MANAGE_API_SCOPE, ANALYTICS_API_SCOPE]

# Where that single token lives. The two legacy files are still read when it
# does not exist yet, so the switch costs exactly one consent, taken whenever
# the next call happens to need a scope the old file lacks - not a flag day.
DEFAULT_TOKEN_PATH = "youtube_token.json"
LEGACY_TOKEN_PATHS = ("upload_token.json", "token.json")

# Which scope implies which. Only supersets go here: demanding a literal match
# would send a token holding `youtube` back through consent to be handed
# `youtube.readonly`, which it already subsumes.
SCOPE_IMPLIES = {MANAGE_API_SCOPE: (DATA_API_SCOPE,)}


def scopes_satisfied(cached: list[str] | None, needed: list[str]) -> bool:
    """True when a token carrying `cached` can make every call `needed` covers."""
    if not cached:
        return False
    covered = set(cached)
    for scope in cached:
        covered.update(SCOPE_IMPLIES.get(scope, ()))
    return all(scope in covered for scope in needed)


def token_scopes(path: str) -> list[str] | None:
    """The scopes a cached token file was issued for, or None if unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("scopes")
    except (OSError, ValueError):
        return None


def resolve_token_path(
    preferred: str,
    needed: list[str],
    *,
    legacy: tuple[str, ...] = LEGACY_TOKEN_PATHS,
    scopes_of=token_scopes,
) -> str:
    """Which token file to read for a call needing `needed`.

    The unified file wins whenever it exists. Before it does, a legacy file
    is used only if it actually carries the scopes for this call - handing an
    upload the read-only token would surface as a 403 from the API instead of
    a consent prompt here, which is the more confusing of the two failures.
    """
    if scopes_of(preferred) is not None:
        return preferred
    for candidate in legacy:
        if scopes_satisfied(scopes_of(candidate), needed):
            return candidate
    return preferred


def revoked_token_message(path: str) -> str:
    """Said out loud before the consent flow opens, because that flow waits on
    a browser and a background run then looks like a hung process - which is
    exactly how four clips sat unpublished for a day on 2026-09-22.
    """
    return (
        f"[warn] {path}: the refresh token no longer works (revoked or expired) - "
        "opening a browser for a fresh consent; approve it to continue"
    )


def load_credentials(
    client_secret_path: str,
    token_path: str = DEFAULT_TOKEN_PATH,
    scopes: list[str] = SCOPES,
):
    """Loads cached OAuth credentials for a call needing `scopes`, refreshing
    an expired token or running the local-server consent flow (opens a browser,
    using client_secret_path's app credentials) when there's no usable token.

    `scopes` says what THIS caller needs; consent always asks for ALL_SCOPES,
    so the file left behind serves every other caller too and the account only
    ever holds one refresh token for this client. A cached token that already
    covers `scopes` is used untouched - widening it would mean a consent the
    caller did not ask for, mid-render.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    source_path = resolve_token_path(token_path, scopes)
    source_file = Path(source_path)
    if source_file.exists():
        # Loaded with the scopes the file itself was issued for, not with the
        # ones being asked for: claiming a scope the token does not carry makes
        # the refresh fail with a scope mismatch instead of the clean
        # "not enough, go get consent" answer scopes_satisfied gives below.
        credentials = Credentials.from_authorized_user_file(str(source_file))

    usable = credentials is not None and scopes_satisfied(
        list(credentials.scopes or []), scopes
    )
    if usable and not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                source_file.write_text(credentials.to_json(), encoding="utf-8")
            except RefreshError:
                # A revoked refresh token ("invalid_grant") used to dead-end
                # the whole publish run with a traceback; a cached token that
                # can't be recovered is exactly the case a fresh consent
                # handles, so fall through to it instead of raising.
                print(revoked_token_message(source_path), file=sys.stderr)
                usable = False
        else:
            usable = False

    if not usable:
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, ALL_SCOPES)
        credentials = flow.run_local_server(port=0)
        # Written to the unified path even when a legacy file was the source:
        # that is how the old files stop being used at all, one consent at a
        # time, without anything having to delete them.
        Path(token_path).write_text(credentials.to_json(), encoding="utf-8")

    return credentials

