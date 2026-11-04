#!/usr/bin/env bash
# ADR p40: restore drill — proves a backup is RECOVERABLE end to end.
#
#   pick latest backup → decrypt → restore into a throwaway test DB →
#   run accounting + multi-tenant health checks → RESTORE VERIFIED / FAILED
#
# A backup you have never restored is not a backup. This is the "0" in the
# 3-2-1-1-0 rule (zero restore errors). Run monthly from cron, or by hand
# before a release / before trusting the offsite copy.
#
# Source selection (first match wins):
#   1. explicit path argument (.dump or .dump.age)
#   2. --from-offsite  → newest vet-*.dump.age under $RCLONE_REMOTE/daily/
#      (needs BACKUP_DECRYPTION_KEY → run from the OPERATOR machine, not cron)
#   3. newest LOCAL plaintext .dump in $BACKUP_DIR (default) — works unattended
#      in VPS cron with NO private key. Falls back to .dump.age only if no
#      plaintext exists (then BACKUP_DECRYPTION_KEY is required).
#
# Cron on the VPS proves dump+restore+audits with the local plaintext copy.
# The encrypted/offsite path (decrypt + download) is verified periodically by
# hand from the operator machine that holds the age private key.
#
# Env:
#   BACKUP_DIR             local dumps dir              default /var/backups/vet
#   COMPOSE_DIR/ENV_FILE/COMPOSE_FILE   as the other scripts
#   BACKUP_DECRYPTION_KEY  age PRIVATE key file         required for .age input
#   RCLONE_REMOTE          remote for --from-offsite    default ""
#
# Exit codes:
#   0  RESTORE VERIFIED (restore + every health check passed)
#   1  precondition failure (including postgres not available)
#   2  restore failed
#   3  one or more health checks failed
#
# Never prints secrets. The DATABASE_URL used to point Django at the test DB is
# passed as a process-scoped env var (NOT on the docker argv), so the DB
# password never lands in the argument list or logs.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/vet}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/vet/app}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-$COMPOSE_DIR/docker-compose.prod.yml}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
BACKUP_DECRYPTION_KEY="${BACKUP_DECRYPTION_KEY:-}"

log() { printf '[restore-drill] %s\n' "$*"; }
err() { printf '[restore-drill][ERR] %s\n' "$*" >&2; }

FROM_OFFSITE="no"
SRC_ARG=""
for a in "$@"; do
  case "$a" in
    --from-offsite) FROM_OFFSITE="yes" ;;
    -*) err "unknown flag: $a"; exit 1 ;;
    *) SRC_ARG="$a" ;;
  esac
done

[ -f "$ENV_FILE" ]     || { err "env not found: $ENV_FILE"; exit 1; }
[ -f "$COMPOSE_FILE" ] || { err "compose not found: $COMPOSE_FILE"; exit 1; }
[ -x "$SCRIPT_DIR/pg-restore.sh" ] || { err "pg-restore.sh not found/executable next to this script"; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_USER:?missing POSTGRES_USER in $ENV_FILE}"
: "${POSTGRES_DB:?missing POSTGRES_DB in $ENV_FILE}"
: "${POSTGRES_PASSWORD:?missing POSTGRES_PASSWORD in $ENV_FILE}"

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

# Un simulacro no levanta servicios: `--no-deps` evita arrancar dependencias, pero
# no comprueba nada. Si postgres no responde, se aborta sin intentar iniciarlo.
compose exec -T postgres pg_isready -q -U "$POSTGRES_USER" -d postgres || {
  err "postgres is not available — start it first; this drill will not."
  exit 1
}

TMP_DL=""
# `if`, not `[ ... ] && ...`: under `set -e` a false test as the last command of an
# EXIT trap replaces the exit status with 1, even after `exit 0`.
cleanup() { if [ -n "$TMP_DL" ]; then rm -rf "$TMP_DL"; fi; }
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 1. Pick the backup to drill.
# ---------------------------------------------------------------------------
if [ -n "$SRC_ARG" ]; then
  SRC="$SRC_ARG"
  [ -f "$SRC" ] || { err "source not found: $SRC"; exit 1; }
elif [ "$FROM_OFFSITE" = "yes" ]; then
  [ -n "$RCLONE_REMOTE" ] || { err "--from-offsite requires RCLONE_REMOTE"; exit 1; }
  command -v rclone >/dev/null 2>&1 || { err "rclone not installed"; exit 1; }
  TMP_DL="$(mktemp -d "${TMPDIR:-/tmp}/vet-drill.XXXXXX")"
  LATEST=$(rclone lsf "$RCLONE_REMOTE/daily/" --include 'vet-*.dump.age' 2>/dev/null | sort | tail -1)
  [ -n "$LATEST" ] || { err "no offsite backups under $RCLONE_REMOTE/daily/"; exit 1; }
  log "downloading $LATEST from offsite"
  rclone copy "$RCLONE_REMOTE/daily/$LATEST" "$TMP_DL/" || { err "offsite download failed"; exit 1; }
  # Best-effort manifest fetch so pg-restore.sh can verify the checksum.
  MAN="${LATEST%.dump.age}.manifest.json"
  rclone copy "$RCLONE_REMOTE/daily/$MAN" "$TMP_DL/" 2>/dev/null || true
  SRC="$TMP_DL/$LATEST"
else
  # Prefer the local plaintext .dump so an unattended VPS cron run needs no
  # private key. Fall back to .age only if no plaintext exists locally.
  SRC=$(ls -1t "$BACKUP_DIR"/vet-*.dump 2>/dev/null | head -1 || true)
  [ -n "$SRC" ] || SRC=$(ls -1t "$BACKUP_DIR"/vet-*.dump.age 2>/dev/null | head -1 || true)
  [ -n "$SRC" ] || { err "no local backups found in $BACKUP_DIR"; exit 1; }
fi
log "drill source: $SRC"

case "$SRC" in
  *.age)
    [ -n "$BACKUP_DECRYPTION_KEY" ] || {
      err "source is encrypted but BACKUP_DECRYPTION_KEY is unset (age private key)."
      exit 1
    } ;;
esac

TS=$(date -u +%Y%m%dT%H%M%SZ)
TARGET_DB="vet_drill_$TS"

# ---------------------------------------------------------------------------
# 2. Restore into the throwaway DB (pg-restore.sh decrypts + prints row counts).
# ---------------------------------------------------------------------------
log "restoring into $TARGET_DB ..."
if ! BACKUP_DECRYPTION_KEY="$BACKUP_DECRYPTION_KEY" \
     COMPOSE_DIR="$COMPOSE_DIR" ENV_FILE="$ENV_FILE" COMPOSE_FILE="$COMPOSE_FILE" \
     "$SCRIPT_DIR/pg-restore.sh" "$SRC" "$TARGET_DB"; then
  err "restore FAILED"
  exit 2
fi

# ---------------------------------------------------------------------------
# 3. Health checks against the RESTORED DB.
# ---------------------------------------------------------------------------
FAIL=0

psql_scalar() {
  compose exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -tAc "$1" 2>/dev/null \
    | tr -d '\r' | head -1
}

check_zero() {
  local label="$1" sql="$2" n
  n=$(psql_scalar "$sql"); n="${n:-ERR}"
  if [ "$n" = "0" ]; then
    log "  OK  $label = 0"
  else
    err "  FAIL $label = $n (expected 0)"
    FAIL=1
  fi
}

log "multi-tenant + financial-sign invariants on $TARGET_DB:"
# Invariant: every row in a tenant-scoped table carries organization_id.
check_zero "invoices without organization"        "SELECT count(*) FROM billing_invoice WHERE organization_id IS NULL;"
check_zero "pets without organization"             "SELECT count(*) FROM patients_pet WHERE organization_id IS NULL;"
check_zero "medical records without organization"  "SELECT count(*) FROM medical_records_medicalrecord WHERE organization_id IS NULL;"
# Invariant 4: financial events always amount > 0 (sign is given by event type).
check_zero "payments with amount <= 0"             "SELECT count(*) FROM billing_payment WHERE amount <= 0;"
check_zero "refund payments with amount <= 0"      "SELECT count(*) FROM billing_refundpayment WHERE amount <= 0;"

PAID=$(psql_scalar "SELECT count(*) FROM billing_invoice WHERE status='paid';")
PAYM=$(psql_scalar "SELECT count(*) FROM billing_payment;")
log "  info: paid invoices=${PAID:-?}  payment events=${PAYM:-?}"

# ---------------------------------------------------------------------------
# 4. GOLD: run the existing accounting audits against the restored DB.
#    DATABASE_URL is exported into THIS process and passed through with `-e
#    DATABASE_URL` (no value on argv) → the password never hits the arg list.
#    DB_CONN_MAX_AGE=0 avoids leaking a pooled connection from a one-shot run.
#    --no-deps: backend depends on `release`, and without it every drill would
#    re-run migrate/collectstatic/seed_permissions against the LIVE database.
# ---------------------------------------------------------------------------
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${PGHOST:-postgres}:${PGPORT:-5432}/${TARGET_DB}"

run_audit() {
  local cmd="$1"
  log "running $cmd against $TARGET_DB ..."
  if compose run --rm --no-deps -e DATABASE_URL -e DB_CONN_MAX_AGE=0 backend \
       python manage.py "$cmd" --json; then
    log "  OK  $cmd exit 0"
  else
    err "  FAIL $cmd reported violations"
    FAIL=1
  fi
}
run_audit audit_anchor_integrity
run_audit audit_payment_ledger_integrity

unset DATABASE_URL

# ---------------------------------------------------------------------------
# 5. Drop the throwaway DB.
# ---------------------------------------------------------------------------
log "dropping $TARGET_DB"
compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$TARGET_DB\";" >/dev/null 2>&1 \
  || err "could not drop $TARGET_DB — drop it manually"

# ---------------------------------------------------------------------------
# 6. Verdict.
# ---------------------------------------------------------------------------
if [ "$FAIL" -eq 0 ]; then
  log "RESTORE VERIFIED  (source: $(basename "$SRC"))"
  exit 0
fi
err "RESTORE FAILED — one or more health checks did not pass"
exit 3
