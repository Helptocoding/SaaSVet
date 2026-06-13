#!/usr/bin/env bash
# Capa 4 (DEPLOY_VPS_PLAN.md) + ADR p40: nightly Postgres backup with offsite,
# client-side encryption, integrity validation and a JSON manifest.
#
# Runs on the VPS host (NOT inside any container). Invoked from cron as user
# `deploy`. Pipeline (ADR p40):
#
#   pg_dump -Fc → pg_restore --list (validate) → sha256 + manifest
#               → age encrypt (PUBLIC key)      → rclone copy to B2 (immutable)
#
# The plaintext dump stays LOCAL only (same trust zone as the live DB on the
# same host). Only the age-encrypted copy ever leaves the host, so B2 holds
# zero-knowledge data: a compromised VPS cannot decrypt historical backups
# because the age PRIVATE key lives offline, never on the server.
#
# Configuration via environment (cron line, wrapper, or .env.prod):
#   BACKUP_DIR                    target dir on host          default /var/backups/vet
#   COMPOSE_DIR                   repo root on VPS            default /opt/vet/app
#   ENV_FILE                      path to .env.prod          default $COMPOSE_DIR/.env.prod
#   RETENTION_DAYS                keep LOCAL artifacts N days default 14
#   RCLONE_REMOTE                 `remote:bucket[/path]`      default ""  (no offsite)
#   BACKUP_ENCRYPTION_PUBLIC_KEY  age recipient (age1...) OR  default ""
#                                 path to a recipients file
#   HEALTHCHECK_URL               healthchecks.io ping URL    default ""  (no ping)
#
# Production guard (ENVIRONMENT=production, read from .env.prod):
#   - RCLONE_REMOTE empty  → FAIL LOUD (exit 6). Local dump is still created/kept.
#   - offsite upload fails → FAIL LOUD (exit 6). Local dump kept; deadman NOT pinged.
#   In any non-production ENVIRONMENT, missing offsite = local-only mode (warn).
#
# Encryption rule: a dump that goes offsite MUST be encrypted. If RCLONE_REMOTE
# is set but `age` or the public key is missing → exit 5. We never upload
# plaintext PII (medical records, billing ledger) to B2.
#
# Exit codes:
#   0  full success (dump + validate + checksum + [encrypt] + [offsite] + retention)
#   1  precondition failure (missing env, compose dir, postgres container down)
#   2  dump file too small or empty — likely streaming failure
#   3  pg_dump itself returned non-zero
#   4  pg_restore --list validation failed — dump is corrupt/unreadable
#   5  encryption required but unavailable (missing age / rclone / public key)
#   6  offsite misconfigured or failed in production
#
# DO NOT add `set -x` in production cron — it would log $POSTGRES_PASSWORD via
# `set -a; . $ENV_FILE`. The age PUBLIC key and the B2 bucket name are NOT
# secrets. The rclone B2 Application Key lives ONLY in rclone.conf (chmod 600),
# never in this script or in .env.prod.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/vet}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/vet/app}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env.prod}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
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

# Backup-flow config — resolved AFTER sourcing so .env.prod may define them,
# with cron/env vars as fallback. Defaults keep local dev in local-only mode.
ENVIRONMENT="${ENVIRONMENT:-development}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
BACKUP_ENCRYPTION_PUBLIC_KEY="${BACKUP_ENCRYPTION_PUBLIC_KEY:-}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"

is_production() { [ "$ENVIRONMENT" = "production" ]; }

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "UNKNOWN"
  fi
}
size_of() { stat -c%s "$1" 2>/dev/null || stat -f%z "$1" 2>/dev/null || echo 0; }

# ---------------------------------------------------------------------------
# Preflight: production offsite enforcement + tooling availability.
# ---------------------------------------------------------------------------

# In production a backup with NO offsite copy defeats the entire point. Fail
# loud BEFORE dumping so the operator can't silently ship without offsite.
if is_production && [ -z "$RCLONE_REMOTE" ]; then
  err "ENVIRONMENT=production but RCLONE_REMOTE is empty — refusing to run a"
  err "backup with no offsite copy. Set RCLONE_REMOTE (remote:bucket) + retry."
  exit 6
fi

# Decide encryption mode.
#   required → going offsite, MUST encrypt.
#   optional → dev with a public key set: encrypt locally as a courtesy.
#   no       → dev, no key: plaintext local only.
ENCRYPT="no"
if [ -n "$RCLONE_REMOTE" ]; then
  ENCRYPT="required"
elif [ -n "$BACKUP_ENCRYPTION_PUBLIC_KEY" ]; then
  ENCRYPT="optional"
fi

if [ "$ENCRYPT" = "required" ]; then
  command -v age >/dev/null 2>&1 || {
    err "offsite requested (RCLONE_REMOTE set) but 'age' is not installed."
    err "Refusing to send plaintext PII offsite. Install age and retry."
    exit 5
  }
  command -v rclone >/dev/null 2>&1 || {
    err "RCLONE_REMOTE set but 'rclone' is not installed."
    exit 5
  }
  [ -n "$BACKUP_ENCRYPTION_PUBLIC_KEY" ] || {
    err "offsite requested but BACKUP_ENCRYPTION_PUBLIC_KEY is empty."
    err "Set the age PUBLIC key (age1...) — never upload an unencrypted dump."
    exit 5
  }
elif [ "$ENCRYPT" = "optional" ] && ! command -v age >/dev/null 2>&1; then
  err "'age' not installed — skipping optional local encryption."
  ENCRYPT="no"
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

TS=$(date -u +%Y%m%dT%H%M%SZ)
DUMP_FILE="$BACKUP_DIR/vet-$TS.dump"
AGE_FILE="$DUMP_FILE.age"
MANIFEST_FILE="$BACKUP_DIR/vet-$TS.manifest.json"

# ---------------------------------------------------------------------------
# 1. pg_dump (-Fc compressed custom format, streamed from the live container).
# ---------------------------------------------------------------------------
log "starting dump → $DUMP_FILE"
if ! compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
       > "$DUMP_FILE"; then
  err "pg_dump failed"
  rm -f "$DUMP_FILE"
  exit 3
fi

DUMP_SIZE=$(size_of "$DUMP_FILE")
if [ "$DUMP_SIZE" -lt 1024 ]; then
  err "dump suspiciously small ($DUMP_SIZE bytes) — deleting"
  rm -f "$DUMP_FILE"
  exit 2
fi
log "dump OK ($DUMP_SIZE bytes)"

# ---------------------------------------------------------------------------
# 2. Validate the archive is readable BEFORE we trust/encrypt/upload it.
#    Pipe it back through the container's pg_restore --list (no host pg client).
# ---------------------------------------------------------------------------
TOC_COUNT=$(compose exec -T postgres pg_restore --list < "$DUMP_FILE" 2>/dev/null \
              | grep -cE '^[0-9]+;' || true)
if [ -z "$TOC_COUNT" ] || [ "$TOC_COUNT" -lt 1 ]; then
  err "pg_restore --list found no TOC entries — dump unreadable/corrupt. Deleting."
  rm -f "$DUMP_FILE"
  exit 4
fi
log "validation OK ($TOC_COUNT TOC entries)"

# ---------------------------------------------------------------------------
# 3. Checksum + Postgres version (for the manifest).
# ---------------------------------------------------------------------------
DUMP_SHA=$(sha256_of "$DUMP_FILE")
PG_VERSION=$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
               -tAc 'SHOW server_version;' 2>/dev/null | tr -d '\r' | head -1 || echo "unknown")
[ -n "$PG_VERSION" ] || PG_VERSION="unknown"
log "sha256(dump)=$DUMP_SHA  pg=$PG_VERSION"

# ---------------------------------------------------------------------------
# 4. age encryption (only the encrypted copy is allowed offsite).
# ---------------------------------------------------------------------------
ENC_SHA=""
ENC_SIZE=""
UPLOAD_FILE="$DUMP_FILE"      # default = plaintext (dev local-only)
ENCRYPTION_LABEL="none"
if [ "$ENCRYPT" != "no" ]; then
  log "encrypting with age → $AGE_FILE"
  if [ -f "$BACKUP_ENCRYPTION_PUBLIC_KEY" ]; then
    AGE_RECIP=(--recipients-file "$BACKUP_ENCRYPTION_PUBLIC_KEY")
  else
    AGE_RECIP=(--recipient "$BACKUP_ENCRYPTION_PUBLIC_KEY")
  fi
  if ! age --encrypt "${AGE_RECIP[@]}" --output "$AGE_FILE" "$DUMP_FILE"; then
    err "age encryption failed"
    rm -f "$AGE_FILE"
    if [ "$ENCRYPT" = "required" ]; then exit 5; fi
  else
    chmod 600 "$AGE_FILE" 2>/dev/null || true
    ENC_SHA=$(sha256_of "$AGE_FILE")
    ENC_SIZE=$(size_of "$AGE_FILE")
    UPLOAD_FILE="$AGE_FILE"
    ENCRYPTION_LABEL="age"
    log "encrypted OK ($ENC_SIZE bytes) sha256=$ENC_SHA"
  fi
fi

# ---------------------------------------------------------------------------
# 5. Manifest. The age recipient (PUBLIC key) is NOT a secret; safe to embed.
# ---------------------------------------------------------------------------
RECIP_JSON="null"
if [ -n "$BACKUP_ENCRYPTION_PUBLIC_KEY" ] && [ ! -f "$BACKUP_ENCRYPTION_PUBLIC_KEY" ]; then
  RECIP_JSON="\"$BACKUP_ENCRYPTION_PUBLIC_KEY\""
fi
ENC_FILE_JSON="null"
ENC_SHA_JSON="null"
if [ -n "$ENC_SHA" ]; then
  ENC_FILE_JSON="\"$(basename "$AGE_FILE")\""
  ENC_SHA_JSON="\"$ENC_SHA\""
fi
cat > "$MANIFEST_FILE" <<JSON
{
  "schema_version": 1,
  "created_utc": "$TS",
  "environment": "$ENVIRONMENT",
  "database": "$POSTGRES_DB",
  "postgres_version": "$PG_VERSION",
  "dump_format": "pg_dump -Fc (custom)",
  "toc_entries": $TOC_COUNT,
  "plaintext_file": "$(basename "$DUMP_FILE")",
  "plaintext_size_bytes": $DUMP_SIZE,
  "plaintext_sha256": "$DUMP_SHA",
  "encryption": "$ENCRYPTION_LABEL",
  "encrypted_file": $ENC_FILE_JSON,
  "encrypted_size_bytes": ${ENC_SIZE:-null},
  "encrypted_sha256": $ENC_SHA_JSON,
  "age_recipient": $RECIP_JSON
}
JSON
chmod 600 "$MANIFEST_FILE" 2>/dev/null || true
log "manifest → $MANIFEST_FILE"

# ---------------------------------------------------------------------------
# 6. Offsite upload (encrypted artifact only). GFS tiers via path prefix.
#    B2 Object Lock + lifecycle rules (configured in the B2 console) own
#    expiry — the no-delete App Key cannot and must not prune.
# ---------------------------------------------------------------------------
OFFSITE_OK="skipped"
if [ -n "$RCLONE_REMOTE" ]; then
  if [ "$ENCRYPTION_LABEL" != "age" ]; then
    err "refusing offsite upload of a non-encrypted dump"
    OFFSITE_OK="failed"
  else
    upload_to() {
      local tier="$1"
      rclone copy --quiet "$UPLOAD_FILE"   "$RCLONE_REMOTE/$tier/" &&
      rclone copy --quiet "$MANIFEST_FILE" "$RCLONE_REMOTE/$tier/"
    }
    if upload_to "daily"; then
      log "offsite daily OK → $RCLONE_REMOTE/daily/"
      OFFSITE_OK="ok"
    else
      err "rclone upload to daily/ failed (local copy still kept)"
      OFFSITE_OK="failed"
    fi
    # Monthly tier: keep the 1st-of-month backup for long-term retention.
    if [ "$(date -u +%d)" = "01" ] && [ "$OFFSITE_OK" = "ok" ]; then
      if upload_to "monthly"; then
        log "offsite monthly OK → $RCLONE_REMOTE/monthly/"
      else
        err "rclone upload to monthly/ failed"
        OFFSITE_OK="failed"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 7. Local retention (plaintext + encrypted + manifest swept together).
#    Offsite retention is owned by B2 lifecycle, NOT by this script.
# ---------------------------------------------------------------------------
DELETED=$(find "$BACKUP_DIR" -maxdepth 1 \
            \( -name 'vet-*.dump' -o -name 'vet-*.dump.age' -o -name 'vet-*.manifest.json' \) \
            -mtime "+$RETENTION_DAYS" -print -delete | wc -l)
log "retention swept ($DELETED file(s) older than ${RETENTION_DAYS}d)"

# ---------------------------------------------------------------------------
# 8. Production offsite enforcement — fail loud so monitoring fires.
# ---------------------------------------------------------------------------
if is_production && [ "$OFFSITE_OK" = "failed" ]; then
  err "offsite copy did NOT complete in production. Local dump retained at"
  err "$UPLOAD_FILE. Deadman ping suppressed so the monitor alerts. Exit 6."
  exit 6
fi

# ---------------------------------------------------------------------------
# 9. Deadman switch — ping ONLY on full success (suppressed on failure above).
# ---------------------------------------------------------------------------
if [ -n "$HEALTHCHECK_URL" ]; then
  curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL" -o /dev/null \
    || err "healthcheck ping failed"
fi

log "done $UPLOAD_FILE (offsite: $OFFSITE_OK)"
