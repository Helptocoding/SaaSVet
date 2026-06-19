#!/usr/bin/env bash
# P1-6B: production deploy orchestrator for the single-node Docker stack.
#
# Run ON THE VPS as user `deploy`, from the repo root:
#   bash scripts/deploy.sh              # deploy current branch HEAD (git pull --ff-only)
#   bash scripts/deploy.sh <git-ref>    # deploy a specific tag/branch/sha
#
# What it does, in order (each phase logged):
#   1. preflight   — compose file, .env.prod, git repo, docker present
#   2. record      — read the currently-live image tag (rollback target)
#   3. update code — git pull --ff-only (or checkout <ref>)
#   4. SHA         — git rev-parse --short HEAD = deploy id + image tag
#   5. BACKUP (H1) — fast local pre-deploy DB snapshot; ABORT if it fails
#   6. GIT_SHA     — upsert GIT_SHA + SENTRY_RELEASE in .env.prod (idempotent)
#   7. build       — IMAGE_TAG=<sha> docker compose build
#   8. release     — migrate + collectstatic + seed_permissions (one-shot)
#   9. up          — IMAGE_TAG=<sha> docker compose up -d
#  10. HEALTH GATE — services healthy + readyz + /api/version == <sha>
#  11. success     — persist deploy state, prune old images
#      OR on failure → AUTOMATIC IMAGE ROLLBACK to the previous tag (no rebuild).
#         The DB is NEVER auto-restored: if migrations ran, the script prints
#         the exact (destructive, human-confirmed) restore command and stops.
#
# Decisions (approved P1-6B): SHA-tagged images + pointer rollback; local fast
# pre-deploy snapshot (not B2); semi-automatic rollback (image auto, DB manual).

set -euo pipefail

LOG_TAG=deploy
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/deploy-lib.sh
. "$SCRIPT_DIR/deploy-lib.sh"

TARGET_REF="${1:-}"

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
[ -f "$COMPOSE_FILE" ] || { err "compose file not found: $COMPOSE_FILE"; exit 1; }
[ -f "$ENV_FILE" ]     || { err ".env.prod not found: $ENV_FILE"; exit 1; }
command -v docker >/dev/null 2>&1 || { err "docker not found in PATH"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "docker compose plugin not available"; exit 1; }
git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { err "not a git repo: $ROOT_DIR"; exit 1; }

load_env

if [ "${ENVIRONMENT:-}" != "production" ]; then
  err "WARN: ENVIRONMENT='${ENVIRONMENT:-unset}' (expected 'production'). Continuing."
fi

# ---------------------------------------------------------------------------
# 2. Record the currently-live tag (rollback target) AND the tag before it, so
#    the rollback chain survives one hop back without collapsing onto itself.
#    Both empty on first scripted deploy.
# ---------------------------------------------------------------------------
PREV_TAG="$(read_state CURRENT_TAG || true)"
PREV_PREV_TAG="$(read_state PREVIOUS_TAG || true)"

# ---------------------------------------------------------------------------
# 3. Update code
# ---------------------------------------------------------------------------
if [ -n "$TARGET_REF" ]; then
  log "fetching origin (tags + prune)..."
  git -C "$ROOT_DIR" fetch --tags --prune origin
  if git -C "$ROOT_DIR" show-ref --verify --quiet "refs/remotes/origin/$TARGET_REF"; then
    # Branch name → deploy the REMOTE tip, not a stale local copy. reset --hard
    # only touches tracked files (.env.prod / .deploy-state are gitignored).
    log "checking out branch $TARGET_REF at origin tip"
    git -C "$ROOT_DIR" checkout --quiet "$TARGET_REF"
    git -C "$ROOT_DIR" reset --hard "origin/$TARGET_REF"
  else
    # Tag or SHA (immutable) → plain checkout.
    log "checking out ref (tag/sha) $TARGET_REF"
    git -C "$ROOT_DIR" checkout --quiet "$TARGET_REF"
  fi
else
  log "git pull --ff-only"
  if ! git -C "$ROOT_DIR" pull --ff-only; then
    err "git pull --ff-only failed (diverged history?). Resolve manually, then retry."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 4. SHA
# ---------------------------------------------------------------------------
SHA="$(current_sha || true)"
[ -n "$SHA" ] || { err "could not resolve git SHA"; exit 1; }
log "deploying SHA=$SHA  (previous live tag: ${PREV_TAG:-none})"

if [ "$SHA" = "$PREV_TAG" ]; then
  err "WARN: $SHA is already the live tag. Re-deploying anyway (rebuild + migrate are idempotent)."
fi

# ---------------------------------------------------------------------------
# 5. Pre-deploy DB snapshot (H1). ABORT the whole deploy if it fails — without a
#    restore point we do not touch migrations.
# ---------------------------------------------------------------------------
log "taking pre-deploy DB snapshot..."
if ! PREDEPLOY="$(bash "$SCRIPT_DIR/pre-deploy-backup.sh" "$SHA")"; then
  err "pre-deploy backup FAILED — aborting deploy (no migration without a restore point)."
  exit 1
fi
log "pre-deploy snapshot ready: $PREDEPLOY"

# ---------------------------------------------------------------------------
# 6. GIT_SHA / SENTRY_RELEASE → .env.prod (so /api/version + Sentry release match
#    the deployed commit; APP_VERSION derives from GIT_SHA in settings.py).
# ---------------------------------------------------------------------------
set_env_var GIT_SHA "$SHA"
set_env_var SENTRY_RELEASE "$SHA"
log "GIT_SHA + SENTRY_RELEASE set to $SHA"

# ---------------------------------------------------------------------------
# 7. Build images tagged with the SHA (release + backend + frontend).
# ---------------------------------------------------------------------------
export IMAGE_TAG="$SHA"
log "building images (IMAGE_TAG=$SHA)..."
compose build

# ---------------------------------------------------------------------------
# 8. Release one-shot: migrate + collectstatic + seed_permissions. From here the
#    schema MAY have advanced → image rollback alone is not guaranteed safe.
# ---------------------------------------------------------------------------
log "running release (migrate + collectstatic + seed_permissions)..."
if ! compose run --rm release; then
  err "release step FAILED (migration error?). Stack NOT switched to $SHA."
  err "DB may be partially migrated. Pre-deploy snapshot: $PREDEPLOY"
  err "Old containers are still running the previous version."
  err "To restore the DB to its pre-deploy state (DESTRUCTIVE, human-confirmed):"
  err "   bash $SCRIPT_DIR/rollback.sh --restore-db $PREDEPLOY"
  exit 1
fi
MIGRATED=1

# ---------------------------------------------------------------------------
# 9. Bring up the new version.
# ---------------------------------------------------------------------------
log "bringing up stack with IMAGE_TAG=$SHA..."
compose up -d

# ---------------------------------------------------------------------------
# 10/11. Health gate → success, or automatic IMAGE rollback.
# ---------------------------------------------------------------------------
if health_gate "$SHA"; then
  external_health
  # Rollback target = the tag we just replaced. On a same-SHA redeploy keep the
  # PRE-EXISTING previous so rollback still has somewhere to go (don't collapse
  # PREVIOUS onto CURRENT).
  if [ "$SHA" = "${PREV_TAG:-}" ]; then NEW_PREV="${PREV_PREV_TAG:-}"; else NEW_PREV="${PREV_TAG:-}"; fi
  write_state "$SHA" "$NEW_PREV" "$PREDEPLOY"
  prune_images "${KEEP_IMAGES:-3}"
  log "DEPLOY OK → live version is now $SHA"
  exit 0
fi

err "health gate failed for $SHA — attempting AUTOMATIC IMAGE ROLLBACK."

if [ -z "${PREV_TAG:-}" ]; then
  err "No previous image tag on record (first scripted deploy?) — cannot auto-rollback the image."
  err "Manual intervention required. Pre-deploy DB snapshot: $PREDEPLOY"
  exit 3
fi

if ! docker image inspect "vet-backend:$PREV_TAG" >/dev/null 2>&1; then
  err "previous image vet-backend:$PREV_TAG is no longer on disk — cannot auto-rollback."
  err "Manual intervention required. Pre-deploy DB snapshot: $PREDEPLOY"
  exit 3
fi

export IMAGE_TAG="$PREV_TAG"
log "rolling back to previous image tag $PREV_TAG..."
compose up -d

if health_gate "$PREV_TAG"; then
  err "ROLLED BACK to previous image $PREV_TAG — service is healthy again on the OLD code."
  # Live is PREV_TAG again; the next rollback target is the tag that preceded it
  # (not PREV_TAG itself — that would make a further rollback a no-op).
  write_state "$PREV_TAG" "${PREV_PREV_TAG:-}" "$PREDEPLOY"
  if [ "${MIGRATED:-0}" = "1" ]; then
    err "IMPORTANT: migrations from $SHA are STILL APPLIED to the database."
    err "If the failure was schema-related, the old code may misbehave against the new schema."
    err "To restore the DB to its pre-deploy state (DESTRUCTIVE, human-confirmed):"
    err "   bash $SCRIPT_DIR/rollback.sh --restore-db $PREDEPLOY"
  fi
  exit 2
fi

err "rolled-back image $PREV_TAG is ALSO unhealthy — manual intervention required."
err "Pre-deploy DB snapshot: $PREDEPLOY"
exit 3
