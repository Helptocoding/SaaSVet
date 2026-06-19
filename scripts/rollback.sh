#!/usr/bin/env bash
# P1-6B: rollback for the single-node Docker stack.
#
# Two levels, matching the approved semi-automatic policy:
#   - IMAGE rollback (default, NON-destructive): re-point IMAGE_TAG to a prior
#     SHA-tagged image already on disk and `up -d`. Seconds, no rebuild, data
#     untouched. Safe when the bad deploy's migrations were additive/none.
#   - DB restore (--restore-db, DESTRUCTIVE): drop + recreate the live DB and
#     restore a pre-deploy snapshot. Required when a bad migration corrupted the
#     schema/data. NEVER automatic — demands explicit human confirmation.
#
# Run ON THE VPS as user `deploy`, from the repo root:
#   bash scripts/rollback.sh                       # → previous image (from .deploy-state)
#   bash scripts/rollback.sh --to <sha>            # → a specific image tag
#   bash scripts/rollback.sh --list                # show state + available images/snapshots
#   bash scripts/rollback.sh --restore-db <dump>   # DESTRUCTIVE DB restore (confirmed)
#
# Exit codes: 0 ok | 1 precondition/abort | 3 unhealthy after rollback

set -euo pipefail

LOG_TAG=rollback
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/deploy-lib.sh
. "$SCRIPT_DIR/deploy-lib.sh"

usage() {
  # Print only the header comment block (help), not the code below it.
  sed -n '2,18p' "$0" >&2
  exit "${1:-1}"
}

MODE="image"
TO=""
DBDUMP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --to)         MODE="image"; TO="${2:?--to needs a SHA}"; shift 2 ;;
    --restore-db) MODE="db";    DBDUMP="${2:?--restore-db needs a dump path}"; shift 2 ;;
    --list)       MODE="list";  shift ;;
    -h|--help)    usage 0 ;;
    *)            err "unknown argument: $1"; usage 1 ;;
  esac
done

[ -f "$COMPOSE_FILE" ] || { err "compose file not found: $COMPOSE_FILE"; exit 1; }
[ -f "$ENV_FILE" ]     || { err ".env.prod not found: $ENV_FILE"; exit 1; }
load_env

CURRENT="$(read_state CURRENT_TAG || true)"
PREV="$(read_state PREVIOUS_TAG || true)"
STATE_PREDEPLOY="$(read_state PREDEPLOY_BACKUP || true)"

# ---------------------------------------------------------------------------
# --list : show what we can roll back to.
# ---------------------------------------------------------------------------
if [ "$MODE" = "list" ]; then
  printf 'Deploy state (%s):\n'                "$STATE_FILE" >&2
  printf '  CURRENT_TAG      = %s\n'           "${CURRENT:-<none>}" >&2
  printf '  PREVIOUS_TAG     = %s\n'           "${PREV:-<none>}" >&2
  printf '  PREDEPLOY_BACKUP = %s\n\n'         "${STATE_PREDEPLOY:-<none>}" >&2
  printf 'Available backend images on disk:\n' >&2
  docker images vet-backend --format '  vet-backend:{{.Tag}}  ({{.CreatedAt}})' 2>/dev/null >&2 || true
  printf '\nLocal pre-deploy snapshots:\n' >&2
  # shellcheck disable=SC2012
  ls -1t "$BACKUP_DIR"/vet-predeploy-*.dump 2>/dev/null | sed 's/^/  /' >&2 || printf '  <none>\n' >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# IMAGE rollback (non-destructive).
# ---------------------------------------------------------------------------
image_rollback() {
  local tag="$1"
  [ -n "$tag" ] || { err "no rollback target tag (nothing in .deploy-state and no --to given)"; exit 1; }
  if ! docker image inspect "vet-backend:$tag" >/dev/null 2>&1; then
    err "image vet-backend:$tag is not on disk — cannot roll back to it."
    err "Run 'bash scripts/rollback.sh --list' to see available tags."
    exit 1
  fi

  printf '\nIMAGE ROLLBACK (non-destructive, data untouched)\n'   >&2
  printf '  current : %s\n'  "${CURRENT:-<unknown>}"               >&2
  printf '  target  : %s\n\n' "$tag"                              >&2
  printf 'Proceed? [y/N] ' >&2
  read -r ans
  case "$ans" in y|Y|yes|YES) ;; *) err "aborted"; exit 1 ;; esac

  export IMAGE_TAG="$tag"
  log "switching stack to image tag $tag..."
  compose up -d
  if health_gate "$tag"; then
    write_state "$tag" "${CURRENT:-}" "${STATE_PREDEPLOY:-}"
    log "IMAGE ROLLBACK OK → live version is now $tag"
    exit 0
  fi
  err "rolled-back image $tag is unhealthy — manual intervention required."
  exit 3
}

# ---------------------------------------------------------------------------
# DB restore (DESTRUCTIVE). Manual confirmation required. Never run from cron.
# ---------------------------------------------------------------------------
db_restore() {
  local dump="$1"
  [ -f "$dump" ] || { err "dump not found: $dump"; exit 1; }
  : "${POSTGRES_USER:?missing POSTGRES_USER in $ENV_FILE}"
  : "${POSTGRES_DB:?missing POSTGRES_DB in $ENV_FILE}"

  cat >&2 <<EOF

============================================================
  DESTRUCTIVE DATABASE RESTORE
============================================================
  This will DROP the live database '$POSTGRES_DB' and restore:
      $dump
  Every change written to the DB AFTER that snapshot was taken
  will be PERMANENTLY LOST.

  After restore, the stack is brought up on the PREVIOUS image
  tag (${PREV:-$CURRENT}) so the code matches the restored schema.
============================================================
EOF
  # Hard gate: never let the destructive restore run unattended. Without a real
  # TTY a piped/redirected/cron stdin could feed the confirmation automatically.
  [ -t 0 ] || { err "refusing destructive DB restore on non-interactive stdin — run it in an interactive shell."; exit 1; }
  printf "Type the database name (%s) to confirm: " "$POSTGRES_DB" >&2
  read -r ans
  if [ "$ans" != "$POSTGRES_DB" ]; then
    err "confirmation did not match '$POSTGRES_DB' — aborted. Nothing changed."
    exit 1
  fi

  # Stop the app so nothing holds connections / writes during the swap.
  log "stopping app containers (backend, release)..."
  compose stop backend release >/dev/null 2>&1 || true

  log "terminating residual connections to $POSTGRES_DB..."
  compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$POSTGRES_DB' AND pid <> pg_backend_pid();" \
    >/dev/null

  log "dropping + recreating $POSTGRES_DB..."
  compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" \
    -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"

  log "restoring snapshot into $POSTGRES_DB..."
  # --no-owner/--no-privileges avoid role-mismatch noise; --exit-on-error fails loud.
  if ! cat "$dump" | compose exec -T postgres \
        pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error; then
    err "pg_restore FAILED. The DB may be empty/partial — investigate before serving traffic."
    exit 3
  fi

  local tag="${PREV:-$CURRENT}"
  if [ -z "$tag" ]; then
    err "no image tag on record to bring the app up. Start it manually:"
    err "   IMAGE_TAG=<sha> docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d"
    exit 3
  fi
  export IMAGE_TAG="$tag"
  log "bringing app up on image tag $tag (matches restored schema)..."
  compose up -d
  if health_gate "$tag"; then
    write_state "$tag" "${CURRENT:-}" "$dump"
    log "DB RESTORE OK — DB restored from snapshot, app healthy on image $tag."
    exit 0
  fi
  err "app unhealthy after DB restore — manual intervention required."
  exit 3
}

case "$MODE" in
  image) image_rollback "${TO:-$PREV}" ;;
  db)    db_restore "$DBDUMP" ;;
  *)     usage 1 ;;
esac
