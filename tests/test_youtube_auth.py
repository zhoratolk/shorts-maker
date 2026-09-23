"""One consent for the whole repo: which token file a call reads, and when
a cached one is no longer enough."""

from scripts.youtube_auth import (
    ALL_SCOPES,
    ANALYTICS_API_SCOPE,
    DATA_API_SCOPE,
    MANAGE_API_SCOPE as UPLOAD_SCOPE,
    resolve_token_path,
    revoked_token_message,
    scopes_satisfied,
)


def test_all_scopes_cover_every_caller_in_this_repo():
    # The whole point of the single file: whatever a caller asks for, the
    # cached token already carries it, so no second consent is ever needed.
    for needed in ([UPLOAD_SCOPE], [DATA_API_SCOPE], [ANALYTICS_API_SCOPE],
                   [DATA_API_SCOPE, ANALYTICS_API_SCOPE]):
        assert scopes_satisfied(ALL_SCOPES, needed)


def test_scopes_satisfied_accepts_an_exact_match():
    assert scopes_satisfied([ANALYTICS_API_SCOPE], [ANALYTICS_API_SCOPE])


def test_scopes_satisfied_treats_manage_as_covering_read_only():
    # `youtube` is a superset of `youtube.readonly` - a token holding the
    # first can read everything the second can, so demanding a literal
    # match would force a pointless extra consent.
    assert scopes_satisfied([UPLOAD_SCOPE], [DATA_API_SCOPE])


def test_scopes_satisfied_rejects_a_token_missing_analytics():
    assert not scopes_satisfied([UPLOAD_SCOPE], [ANALYTICS_API_SCOPE])


def test_scopes_satisfied_rejects_read_only_for_an_upload():
    assert not scopes_satisfied([DATA_API_SCOPE], [UPLOAD_SCOPE])


def test_resolve_token_path_prefers_the_unified_file():
    scopes = {"youtube_token.json": ALL_SCOPES, "upload_token.json": [UPLOAD_SCOPE]}
    assert resolve_token_path(
        "youtube_token.json", [UPLOAD_SCOPE], scopes_of=scopes.get
    ) == "youtube_token.json"


def test_resolve_token_path_falls_back_to_a_legacy_token_that_still_covers_it():
    # Migration: the unified file does not exist until the next consent, and
    # until then an upload must keep working off the token that already has
    # the scope for it.
    scopes = {"upload_token.json": [UPLOAD_SCOPE]}
    assert resolve_token_path(
        "youtube_token.json", [UPLOAD_SCOPE], scopes_of=scopes.get
    ) == "upload_token.json"


def test_resolve_token_path_ignores_a_legacy_token_too_narrow_for_the_call():
    # The read-only token cannot serve an upload; returning it would fail at
    # the API with a 403 instead of asking for consent here.
    scopes = {"token.json": [DATA_API_SCOPE, ANALYTICS_API_SCOPE]}
    assert resolve_token_path(
        "youtube_token.json", [UPLOAD_SCOPE], scopes_of=scopes.get
    ) == "youtube_token.json"


def test_resolve_token_path_returns_the_preferred_path_when_nothing_exists():
    assert resolve_token_path(
        "youtube_token.json", [UPLOAD_SCOPE], scopes_of=lambda path: None
    ) == "youtube_token.json"


def test_revoked_token_message_names_the_file_and_what_to_do():
    # A revoked refresh token used to surface as a silently hung process:
    # the loader fell straight into the consent flow, which waits on a
    # browser that nobody was told to open (2026-09-22, four clips stuck).
    message = revoked_token_message("youtube_token.json")
    assert "youtube_token.json" in message
    assert "refresh" in message.lower()
