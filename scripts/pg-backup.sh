#!/usr/bin/env bash
# Capa 4 (DEPLOY_VPS_PLAN.md): nightly Postgres backup.
#
# Runs on the VPS host (NOT inside any container). Invoked from cron as
# user `deploy`. Calls `docker compose exec postgres pg_dump` to stream a
# custom-format dump to a host directory, then optionally uploads to an
# offsite bucket and pings a deadman-switch URL.
#
# Configuration via environment (override on cron line or in a wrapper):
#   BACKUP_DIR        target dir on host                 default /var/backups/vet
#   COMPOSE_DIR       repo root on VPS                   default /opt/vet/app
#   ENV_FILE          path to .env.prod                  default $COMPOSE_DIR/.env.prod
#   RETENTION_DAYS    keep local dumps for N days        default 14
#   RCLONE_REMOTE     `remote:bucket/path` (skip if "")  default ""  (no offsite)
#   HEALTHCHECK_URL   healthchecks.io ping URL           default ""  (no ping)
#
# Exit codes:
#   0  dump created, size validated, retention applied
#   1  precondition failure (missing env, compose dir, postgres container down)
#   2  dump file too small or empty — likely streaming failure
#   3  pg_dump itself returned non-zero
#
# DO NOT add `set -x` in production cron — would log $POSTGRES_PASSWORD via
# `set -a; . $ENV_FILE`.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/vet}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/vet/app}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env.prod}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"
COMPOSE_FILE="${COMPOSE_FILE:-$COMPOSE_DIR/docker-compose.prod.yml}"

log() { printf '[pg-backup] %s\n' "$*"; }
err() { printf '[pg-backup][ERR] %s\n' "$*" >&2; }

[ -d "$COMPOSE_DIR" ]  || { err "COMPOSE_DIR not found: $COMPOSE_DIR"; exit 1; }
[ -f "$ENV_FILE" ]     || { err "ENV_FILE not found: $ENV_FILE"; exit 1; }
[ -f "$COMPOSE_FILE" ] || { err "COMPOSE_FILE not found: $COMPOSE_FILE"; exit 1; }

# Source env without echoing it.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_USER:?missing POSTGRES_USER in $ENV_FILE}"
: "${POSTGRES_DB:?missing POSTGRES_DB in $ENV_FILE}"

mkdir -p "$BACKUP_DIR"

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT_FILE="$BACKUP_DIR/vet-$TS.dump"

log "starting dump → $OUT_FILE"

# `pg_dump -Fc` = compressed custom format. `-Z 6` = mid compression
# (default 6 is fine; bump to 9 for max compression / max CPU).
# Run via compose exec -T (no TTY, safe for cron) directly on the running
# postgres service — avoids client/server libpq version mismatches on host.
if ! docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
       exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
       > "$OUT_FILE"; then
  err "pg_dump failed"
  rm -f "$OUT_FILE"
  exit 3
fi

# Sanity-check: a successful Postgres dump for this app is always >> 1KB.
SIZE=$(stat -c%s "$OUT_FILE" 2>/dev/null || stat -f%z "$OUT_FILE" 2>/dev/null || echo 0)
if [ "$SIZE" -lt 1024 ]; then
  err "dump suspiciously small ($SIZE bytes) — deleting"
  rm -f "$OUT_FILE"
  exit 2
fi
log "dump OK ($SIZE bytes)"

# Local retention.
DELETED=$(find "$BACKUP_DIR" -maxdepth 1 -name 'vet-*.dump' -mtime "+$RETENTION_DAYS" -print -delete | wc -l)
log "retention swept ($DELETED file(s) older than ${RETENTION_DAYS}d)"

# Offsite upload (optional, won't fail the backup if it fails).
if [ -n "$RCLONE_REMOTE" ]; then
  if rclone copy --quiet "$OUT_FILE" "$RCLONE_REMOTE"; then
    log "offsite OK → $RCLONE_REMOTE"
  else
    err "rclone upload failed (local dump still kept)"
  fi
fi

# Deadman switch (optional).
if [ -n "$HEALTHCHECK_URL" ]; then
  curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL" -o /dev/null || \
    err "healthcheck ping failed"
fi

log "done $OUT_FILE"
