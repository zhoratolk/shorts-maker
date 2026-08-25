#!/usr/bin/env bash
# Notices new recordings and does the slow, judgement-free half of the pipeline on them.
#
# Run from a timer. Each pass: work out which finished recordings exist - joining a
# session's parts into one file where there were several - then transcribe and chunk
# anything not done yet. Both steps are safe to repeat: joining skips a destination that
# already exists and ingest caches every artefact it makes, so an interrupted pass simply
# continues on the next one.
#
# It stops there on purpose. What comes next is choosing which moments are worth clipping,
# and that is judgement rather than computation. This gets the hours of GPU work out of
# the way so that step starts with everything already in front of it.
set -euo pipefail

ROOT=${SHORTS_ROOT:-/srv/shorts-maker}
MEDIA=${SHORTS_MEDIA:-/srv/media}
STATE="$ROOT/work/_auto"

mkdir -p "$STATE" "$MEDIA/clips/sources"

# A pass can run for hours - a three hour stream is a long transcription - and the timer
# keeps firing while it does. Without this they would pile up onto the same card and each
# make the others slower.
exec 9>"$STATE/.lock"
if ! flock -n 9; then
    echo "a pass is already running, leaving this one alone"
    exit 0
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "looking for finished recordings"

# The manifest is a file rather than this script reading stdout: the container's base
# image prints a licence notice on every start, and a caller parsing that would try to
# transcribe the greeting. A single-part recording is used where it lies and never
# appears in the joined directory, so globbing that directory would miss it entirely -
# which is most recordings.
manifest="$STATE/sessions.txt"
: > "$manifest"
shorts python3 deploy/session.py /media/recordings \
    --into /media/clips/sources \
    --manifest /app/work/_auto/sessions.txt

while IFS= read -r source; do
    [ -n "$source" ] || continue
    name=$(basename "$source")
    stem=${name%.*}
    marker="$STATE/$stem.ingested"

    [ -f "$marker" ] && continue

    log "ingesting $name"
    # The marker is written only on success, so a failed run is retried next pass rather
    # than being remembered as done.
    if shorts ingest "$source"; then
        date -Is > "$marker"
        log "ready for moment selection: $name"
    else
        log "ingest failed for $name - will try again next pass"
    fi
done < "$manifest"

log "pass finished"
