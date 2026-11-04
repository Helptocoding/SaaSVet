#!/usr/bin/env bash
# Capa 4 (DEPLOY_VPS_PLAN.md) + ADR p40: restore a pg_dump file into a TEST
# database. Accepts both plaintext `.dump` and age-encrypted `.dump.age`.
#
# DESIGNED FOR RESTORE VERIFICATION, NOT FOR REPLACING PRODUCTION DATA.
# Restores into a NEW database (default `vet_restore_test`) so production
# is untouched. To actually replace production data after a disaster,
# read docs/runbooks/RUNBOOK-RESTORE.md.
#
# Usage:
#   scripts/pg-restore.sh /var/backups/vet/vet-20260524T030000Z.dump
#   scripts/pg-restore.sh /path/to/dump.dump my_target_db
#   BACKUP_DECRYPTION_KEY=~/keys/age.key \
#     scripts/pg-restore.sh /var/backups/vet/vet-...dump.age vet_restore_test
#
# Encrypted input (ADR p40):
#   If the file ends in `.age`, BACKUP_DECRYPTION_KEY must point to the age
#   PRIVATE key file. That key lives OFFLINE / on the operator machine — it is
#   NEVER stored on the VPS. The decrypted plaintext is written to a 0600 temp
#   file and wiped on exit (it holds full PII).
#   If a sibling `<name>.manifest.json` exists, the decrypted dump's sha256 is
#   verified against `plaintext_sha256` before restore.
#
# After restore, prints row counts on critical tables. Compare to a recent
# `SELECT count(*) FROM users_user` against the live DB to sanity-check
# the dump integrity. Numbers should be EQUAL (or within minutes-of-deltas
# if production is still receiving writes).

set -euo pipefail

DUMP_FILE="${1:?usage: pg-restore.sh <dump-file|dump.age> [target-db-name]}"
TARGET_DB="${2:-vet_restore_test}"
BACKUP_DECRYPTION_KEY="${BACKUP_DECRYPTION_KEY:-}"

COMPOSE_DIR="${COMPOSE_DIR:-/opt/vet/app}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-$COMPOSE_DIR/docker-compose.prod.yml}"

log() { printf '[pg-restore] %s\n' "$*"; }
err() { printf '[pg-restore][ERR] %s\n' "$*" >&2; }

[ -f "$DUMP_FILE" ]    || { err "dump not found: $DUMP_FILE"; exit 1; }
[ -f "$ENV_FILE" ]     || { err "env not found: $ENV_FILE"; exit 1; }
[ -f "$COMPOSE_FILE" ] || { err "compose not found: $COMPOSE_FILE"; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${POSTGRES_USER:?missing POSTGRES_USER in $ENV_FILE}"
: "${POSTGRES_DB:?missing POSTGRES_DB in $ENV_FILE}"

# Guard rail: NEVER target the live DB name through this script.
if [ "$TARGET_DB" = "$POSTGRES_DB" ]; then
  err "refusing to restore into the live DB '$POSTGRES_DB'. Use a different target name."
  err "If you really want to replace production, do it manually after reading the runbook."
  exit 1
fi

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "UNKNOWN"
  fi
}

# ---- decrypt if the input is age-encrypted (ADR p40) ----
# RESTORE_SRC is what pg_restore actually reads: the original file for a plain
# .dump, or a 0600 temp holding the decrypted plaintext for a .dump.age.
RESTORE_SRC="$DUMP_FILE"
DECRYPTED_TMP=""
# `if`, not `[ ... ] && ...`: under `set -e` a false test as the last command of an
# EXIT trap replaces the exit status with 1, even after `exit 0`.
cleanup() { if [ -n "$DECRYPTED_TMP" ]; then rm -f "$DECRYPTED_TMP"; fi; }
trap cleanup EXIT INT TERM

case "$DUMP_FILE" in
  *.age)
    command -v age >/dev/null 2>&1 || { err "'age' not installed — cannot decrypt"; exit 1; }
    [ -n "$BACKUP_DECRYPTION_KEY" ] || {
      err "input is encrypted (.age) but BACKUP_DECRYPTION_KEY is unset."
      err "Point it at the age PRIVATE key file (operator machine, NOT the VPS)."
      exit 1
    }
    [ -f "$BACKUP_DECRYPTION_KEY" ] || { err "age identity not found: $BACKUP_DECRYPTION_KEY"; exit 1; }
    DECRYPTED_TMP="$(mktemp "${TMPDIR:-/tmp}/vet-restore.XXXXXX.dump")"
    RESTORE_SRC="$DECRYPTED_TMP"
    log "decrypting $DUMP_FILE → (temp, 0600, wiped on exit)"
    if ! age --decrypt --identity "$BACKUP_DECRYPTION_KEY" --output "$RESTORE_SRC" "$DUMP_FILE"; then
      err "age decryption failed (wrong key? corrupt file?)"
      exit 1
    fi
    log "decrypt OK"
    ;;
esac

# ---- optional integrity check against a sibling manifest ----
MANIFEST_GUESS="${DUMP_FILE%.age}"
MANIFEST_GUESS="${MANIFEST_GUESS%.dump}.manifest.json"
if [ -f "$MANIFEST_GUESS" ]; then
  WANT_SHA=$(grep -oE '"plaintext_sha256"[[:space:]]*:[[:space:]]*"[a-f0-9]{64}"' "$MANIFEST_GUESS" \
               | grep -oE '[a-f0-9]{64}' | head -1 || true)
  if [ -n "$WANT_SHA" ]; then
    GOT_SHA=$(sha256_of "$RESTORE_SRC")
    if [ "$WANT_SHA" = "$GOT_SHA" ]; then
      log "checksum verified against manifest ($MANIFEST_GUESS)"
    else
      err "CHECKSUM MISMATCH vs manifest — refusing to restore a tampered/corrupt dump."
      err "  manifest: $WANT_SHA"
      err "  actual:   $GOT_SHA"
      exit 1
    fi
  fi
fi

PSQL="docker compose -f $COMPOSE_FILE --env-file $ENV_FILE exec -T postgres psql -U $POSTGRES_USER"

log "DROP + CREATE $TARGET_DB"
$PSQL -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$TARGET_DB\";"
$PSQL -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$TARGET_DB\" OWNER \"$POSTGRES_USER\";"

log "streaming pg_restore into $TARGET_DB"
# --no-owner / --no-privileges avoid ROLE mismatch noise when the dump
# was made under a different cluster (e.g., restoring a prod dump onto
# a staging cluster with a different role name).
# --exit-on-error makes pg_restore fail loudly instead of silently
# skipping objects on first error.
cat "$RESTORE_SRC" | docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
  exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$TARGET_DB" \
  --no-owner --no-privileges --exit-on-error

log "row counts (sanity check):"
$PSQL -d "$TARGET_DB" -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'users_user'            AS table, COUNT(*) AS rows FROM users_user
UNION ALL SELECT 'organizations_organization', COUNT(*) FROM organizations_organization
UNION ALL SELECT 'patients_pet',                COUNT(*) FROM patients_pet
UNION ALL SELECT 'patients_owner',              COUNT(*) FROM patients_owner
UNION ALL SELECT 'appointments_appointment',    COUNT(*) FROM appointments_appointment
UNION ALL SELECT 'medical_records_medicalrecord', COUNT(*) FROM medical_records_medicalrecord
UNION ALL SELECT 'billing_invoice',             COUNT(*) FROM billing_invoice
UNION ALL SELECT 'billing_invoiceitem',         COUNT(*) FROM billing_invoiceitem
UNION ALL SELECT 'inventory_product',           COUNT(*) FROM inventory_product
UNION ALL SELECT 'inventory_presentation',      COUNT(*) FROM inventory_presentation
UNION ALL SELECT 'inventory_stockmovement',     COUNT(*) FROM inventory_stockmovement
UNION ALL SELECT 'prescriptions_prescription',  COUNT(*) FROM prescriptions_prescription
;
SQL

cat <<EOM

OK — restored to database '$TARGET_DB' on the live postgres container.

Next steps:
  - Compare row counts against live DB to confirm dump completeness.
  - When done, drop the test DB:
      docker compose -f $COMPOSE_FILE --env-file $ENV_FILE exec -T postgres \\
        psql -U $POSTGRES_USER -d postgres -c 'DROP DATABASE "$TARGET_DB";'
EOM
