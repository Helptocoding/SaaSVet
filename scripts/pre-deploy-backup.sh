#!/usr/bin/env bash
# P1-6B: fast LOCAL pre-deploy DB snapshot — the rollback restore point.
#
# This is NOT the disaster-recovery backup. The encrypted offsite B2 pipeline
# (scripts/pg-backup.sh, ADR p40) stays untouched and owns DR. This snapshot is:
#   - local plaintext (same trust zone as the live DB on the same host),
#   - taken immediately BEFORE migrations run,
#   - validated readable (pg_restore --list),
#   - named by the SHA being deployed,
#   - short-lived (kept only for the last few deploys).
#
# Used by rollback.sh --restore-db when a deploy's migration turns out bad.
#
# Usage:
#   scripts/pre-deploy-backup.sh [SHA]      # SHA defaults to current git HEAD
#
# Prints the dump path on STDOUT (last line) so deploy.sh can capture it.
# All other output goes to STDERR.
#
# Exit codes: 0 ok | 1 precondition | 2 dump too small | 3 pg_dump failed
#             4 validation failed (unreadable/corrupt)

set -euo pipefail

LOG_TAG=predeploy
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/deploy-lib.sh
. "$SCRIPT_DIR/deploy-lib.sh"

SHA="${1:-$(current_sha)}"
load_env

: "${POSTGRES_USER:?missing POSTGRES_USER in $ENV_FILE}"
: "${POSTGRES_DB:?missing POSTGRES_DB in $ENV_FILE}"

# Postgres must be up to dump from it.
if [ "$(_service_health postgres)" != "healthy" ]; then
  err "postgres container is not healthy — cannot take a pre-deploy snapshot."
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

OUT="$BACKUP_DIR/vet-predeploy-$SHA.dump"
log "pre-deploy snapshot → $OUT  (DB state BEFORE deploying $SHA)"

if ! compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUT"; then
  err "pg_dump failed"
  rm -f "$OUT"
  exit 3
fi

SIZE="$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null || echo 0)"
if [ "$SIZE" -lt 1024 ]; then
  err "snapshot suspiciously small ($SIZE bytes) — deleting"
  rm -f "$OUT"
  exit 2
fi

# Validate the archive is actually readable before we trust it as a restore point.
TOC="$(compose exec -T postgres pg_restore --list < "$OUT" 2>/dev/null | grep -cE '^[0-9]+;' || true)"
if [ -z "$TOC" ] || [ "$TOC" -lt 1 ]; then
  err "pg_restore --list found no TOC entries — snapshot unreadable. Deleting."
  rm -f "$OUT"
  exit 4
fi
log "snapshot OK ($SIZE bytes, $TOC TOC entries)"

# Retention: keep the newest N pre-deploy snapshots, drop older (rollback points
# for the last few deploys only). Offsite DR retention is owned by B2, not here.
KEEP="${PREDEPLOY_KEEP:-5}"
# shellcheck disable=SC2012
ls -1t "$BACKUP_DIR"/vet-predeploy-*.dump 2>/dev/null | tail -n +"$((KEEP+1))" | while IFS= read -r old; do
  rm -f "$old" && log "retention: removed old snapshot $(basename "$old")"
done

# The ONLY stdout line: the path, for $(...) capture by deploy.sh.
printf '%s\n' "$OUT"
