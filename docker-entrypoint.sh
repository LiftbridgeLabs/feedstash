#!/bin/sh
# Runs FeedStash as PUID:PGID (default 1000:1000) and makes sure that user can write to the data folder.
# unRAID: PUID=99 PGID=100 (nobody:users). Synology and other NAS: the uid/gid that owns the shared folder.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA_DIR="$(dirname "${DATABASE_PATH:-/data/feedstash.db}")"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    # Only fix ownership when it's wrong: walking a big uploads folder on every start would be slow.
    if [ "$(stat -c %u:%g "$DATA_DIR")" != "$PUID:$PGID" ]; then
        echo "feedstash: making $DATA_DIR writable for $PUID:$PGID"
        chown -R "$PUID:$PGID" "$DATA_DIR" \
            || echo "feedstash: couldn't change the owner of $DATA_DIR; make sure $PUID:$PGID can write to it" >&2
    fi
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$@"
fi

# Started as a non-root user already (docker run --user ...): nothing to change.
exec "$@"
