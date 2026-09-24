#!/bin/sh
# Runs FeedStash as PUID:PGID (default 1000:1000) and makes sure that user can write to the data folder.
# unRAID: PUID=99 PGID=100 (nobody:users). Synology and other NAS: the uid/gid that owns the shared folder.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA_DIR="$(dirname "${DATABASE_PATH:-/data/feedstash.db}")"

case "$PUID$PGID" in
    ''|*[!0-9]*)
        echo "feedstash: PUID and PGID must be numbers (got PUID=$PUID PGID=$PGID)" >&2
        exit 1
        ;;
esac

if [ "$(id -u)" = "0" ]; then
    if [ "$PUID" = "0" ]; then
        echo "feedstash: PUID=0 runs FeedStash as root; set PUID/PGID to the user that owns your data folder" >&2
    fi
    mkdir -p "$DATA_DIR"
    # Only fix ownership when it's wrong: walking a big uploads folder on every start would be slow.
    if [ "$(stat -c %u:%g "$DATA_DIR")" != "$PUID:$PGID" ]; then
        echo "feedstash: making $DATA_DIR writable for $PUID:$PGID"
        # -h: change links themselves, never what they point to.
        if ! chown -R -h "$PUID:$PGID" "$DATA_DIR"; then
            echo "feedstash: couldn't change the owner of $DATA_DIR; make sure $PUID:$PGID can write to it" >&2
            exit 1
        fi
    fi
    # HOME would still say /root after dropping privileges; nothing should try to write there.
    export HOME="$DATA_DIR"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$@"
fi

# Started as a non-root user already (docker run --user ...): nothing to change.
exec "$@"
