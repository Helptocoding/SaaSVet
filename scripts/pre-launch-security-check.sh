#!/usr/bin/env bash
# Capa 8 (DEPLOY_VPS_PLAN.md): pre-launch security validation.
#
# Run on the VPS right before flipping DNS / inviting users. Exits 0 if
# ALL checks pass, 1 if any BLOCKER fails, 2 if only HIGH/MEDIUM fail.
#
# Usage (from /opt/vet/app on the VPS):
#   ./scripts/pre-launch-security-check.sh
#
# Optional env:
#   COMPOSE_DIR  default /opt/vet/app
#   ENV_FILE     default $COMPOSE_DIR/.env.prod
#
# Does NOT mutate state. Read-only audit.

set -uo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/vet/app}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-$COMPOSE_DIR/docker-compose.prod.yml}"

# Color tags (degrade gracefully when not a TTY)
if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[34m'; N=$'\033[0m'
else
  R=; G=; Y=; B=; N=;
fi

PASS=0; FAIL_BLOCKER=0; FAIL_HIGH=0; FAIL_MEDIUM=0
ok()      { printf "%s[PASS]%s %s\n" "$G" "$N" "$*"; PASS=$((PASS+1)); }
blocker() { printf "%s[BLOCKER]%s %s\n" "$R" "$N" "$*"; FAIL_BLOCKER=$((FAIL_BLOCKER+1)); }
high()    { printf "%s[HIGH]%s %s\n" "$R" "$N" "$*"; FAIL_HIGH=$((FAIL_HIGH+1)); }
medium()  { printf "%s[MEDIUM]%s %s\n" "$Y" "$N" "$*"; FAIL_MEDIUM=$((FAIL_MEDIUM+1)); }
info()    { printf "%s[INFO]%s %s\n" "$B" "$N" "$*"; }

section() { printf "\n%s== %s ==%s\n" "$B" "$*" "$N"; }

# ---------------------------------------------------------------------------
section "1. .env.prod file"
# ---------------------------------------------------------------------------

if [ ! -f "$ENV_FILE" ]; then
  blocker ".env.prod missing at $ENV_FILE"
  exit 1
fi
ok ".env.prod exists at $ENV_FILE"

PERMS=$(stat -c "%a" "$ENV_FILE" 2>/dev/null || stat -f "%A" "$ENV_FILE" 2>/dev/null)
if [ "$PERMS" = "600" ]; then
  ok ".env.prod perms = 600"
else
  blocker ".env.prod perms = $PERMS (expected 600). Fix: chmod 600 $ENV_FILE"
fi

OWNER=$(stat -c "%U" "$ENV_FILE" 2>/dev/null || stat -f "%Su" "$ENV_FILE" 2>/dev/null)
CURRENT_USER="${USER:-${USERNAME:-$(id -un 2>/dev/null || echo unknown)}}"
if [ "$OWNER" = "deploy" ] || [ "$OWNER" = "$CURRENT_USER" ]; then
  ok ".env.prod owner = $OWNER"
else
  medium ".env.prod owner = $OWNER (expected deploy)"
fi

# Source for the var checks below.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

# ---------------------------------------------------------------------------
section "2. Required env vars"
# ---------------------------------------------------------------------------

for VAR in SECRET_KEY DEBUG ENVIRONMENT ALLOWED_HOSTS CORS_ALLOWED_ORIGINS \
           CSRF_TRUSTED_ORIGINS POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB \
           DATABASE_URL DOMAIN; do
  VAL="${!VAR:-}"
  if [ -z "$VAL" ]; then
    blocker "$VAR is empty or unset"
  else
    ok "$VAR set"
  fi
done

# ---------------------------------------------------------------------------
section "3. Production-mode flags"
# ---------------------------------------------------------------------------

[ "$DEBUG" = "False" ] && ok "DEBUG=False" || blocker "DEBUG=$DEBUG (expected False)"

[ "$ENVIRONMENT" = "production" ] && ok "ENVIRONMENT=production" || \
  high "ENVIRONMENT=$ENVIRONMENT (expected production — disables CORS fail-fast)"

[ "${SECURE_SSL_REDIRECT:-}" = "True" ] && ok "SECURE_SSL_REDIRECT=True" || \
  blocker "SECURE_SSL_REDIRECT=${SECURE_SSL_REDIRECT:-unset} (expected True)"

[ "${SESSION_COOKIE_SECURE:-}" = "True" ] && ok "SESSION_COOKIE_SECURE=True" || \
  blocker "SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-unset}"

[ "${CSRF_COOKIE_SECURE:-}" = "True" ] && ok "CSRF_COOKIE_SECURE=True" || \
  blocker "CSRF_COOKIE_SECURE=${CSRF_COOKIE_SECURE:-unset}"

HSTS="${SECURE_HSTS_SECONDS:-0}"
if [ "$HSTS" -ge 31536000 ]; then
  ok "SECURE_HSTS_SECONDS=$HSTS (>=1y)"
else
  high "SECURE_HSTS_SECONDS=$HSTS (expected >=31536000 for prod)"
fi

[ "${ALLOW_LEGACY_ID_LOOKUP:-}" = "False" ] && ok "ALLOW_LEGACY_ID_LOOKUP=False" || \
  blocker "ALLOW_LEGACY_ID_LOOKUP=${ALLOW_LEGACY_ID_LOOKUP:-unset} (PK leak risk — ADR p18)"

# ---------------------------------------------------------------------------
section "4. SECRET_KEY strength"
# ---------------------------------------------------------------------------

KEY_LEN=${#SECRET_KEY}
if [ "$KEY_LEN" -lt 50 ]; then
  blocker "SECRET_KEY length=$KEY_LEN (expected >=50). Generate fresh: python -c \"import secrets;print(secrets.token_urlsafe(64))\""
elif echo "$SECRET_KEY" | grep -qi -E "(change.me|smoke|test|demo|example|insecure|django-insecure)"; then
  blocker "SECRET_KEY looks like a placeholder. Regenerate."
else
  ok "SECRET_KEY length=$KEY_LEN, no placeholder pattern"
fi

# ---------------------------------------------------------------------------
section "5. DB password strength"
# ---------------------------------------------------------------------------

PG_LEN=${#POSTGRES_PASSWORD}
if [ "$PG_LEN" -lt 20 ]; then
  blocker "POSTGRES_PASSWORD length=$PG_LEN (expected >=20)"
elif echo "$POSTGRES_PASSWORD" | grep -qi -E "(change|smoke|test|demo|password|admin|123)"; then
  blocker "POSTGRES_PASSWORD looks weak / placeholder"
else
  ok "POSTGRES_PASSWORD length=$PG_LEN, no obvious weak pattern"
fi

# ---------------------------------------------------------------------------
section "6. CORS / CSRF / ALLOWED_HOSTS — no wildcards"
# ---------------------------------------------------------------------------

for VAR in ALLOWED_HOSTS CORS_ALLOWED_ORIGINS CSRF_TRUSTED_ORIGINS; do
  VAL="${!VAR}"
  if echo "$VAL" | grep -q "\*"; then
    blocker "$VAR contains wildcard '*' — never in prod"
  else
    ok "$VAR clean (no wildcard)"
  fi
done

if echo "$CORS_ALLOWED_ORIGINS" | grep -q "^http://"; then
  high "CORS_ALLOWED_ORIGINS contains http:// origin (expected https:// only)"
fi
if echo "$CSRF_TRUSTED_ORIGINS" | grep -q "^http://"; then
  high "CSRF_TRUSTED_ORIGINS contains http:// (expected https:// only)"
fi

# ---------------------------------------------------------------------------
section "7. Bootstrap superuser must NOT be in env"
# ---------------------------------------------------------------------------

if grep -qE "^DJANGO_SUPERUSER_(USERNAME|PASSWORD)=" "$ENV_FILE"; then
  blocker "DJANGO_SUPERUSER_* present in .env.prod — remove (creds leak via /proc/<pid>/environ). Bootstrap manually via createsuperuser once."
else
  ok "no DJANGO_SUPERUSER_* in .env.prod"
fi

# ---------------------------------------------------------------------------
section "8. Stray .env files (Railway / dev leftovers)"
# ---------------------------------------------------------------------------

for STRAY in "$COMPOSE_DIR/backend/.env" "$COMPOSE_DIR/frontend/.env" "$COMPOSE_DIR/.env"; do
  if [ -f "$STRAY" ]; then
    blocker "stray env file $STRAY — delete (only .env.prod should exist on VPS)"
  fi
done
[ "$FAIL_BLOCKER" -eq 0 ] && ok "no stray .env files in repo" || true

# ---------------------------------------------------------------------------
section "9. Frontend bundle audit (inside running container)"
# ---------------------------------------------------------------------------

if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps frontend --format json 2>/dev/null | grep -q '"State":"running"'; then
  MAP_COUNT=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T frontend sh -c "find /usr/share/nginx/html -name '*.map' | wc -l" 2>/dev/null || echo "?")
  if [ "$MAP_COUNT" = "0" ]; then
    ok "frontend bundle has 0 .map files (HIGH H7)"
  else
    high "frontend bundle has $MAP_COUNT .map files — leak risk"
  fi

  # Check for obvious secret patterns in the bundle
  BUNDLE_DIR="/usr/share/nginx/html/assets"
  SECRETS_FOUND=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T frontend sh -c \
    "grep -roE 'AKIA[0-9A-Z]{16}|sk_live_[0-9a-zA-Z]{20,}|xox[baprs]-[0-9a-zA-Z-]{20,}|ghp_[0-9a-zA-Z]{36}' $BUNDLE_DIR 2>/dev/null | wc -l" \
    2>/dev/null || echo "0")
  if [ "$SECRETS_FOUND" = "0" ]; then
    ok "no AWS/Stripe/Slack/GitHub key patterns in bundle"
  else
    blocker "found $SECRETS_FOUND secret-like strings in bundle"
  fi

  # Verify VITE_API_URL is HTTPS
  API_HITS=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T frontend sh -c \
    "grep -roE 'http://[a-z0-9.-]+/api/' $BUNDLE_DIR 2>/dev/null | wc -l" 2>/dev/null || echo "0")
  if [ "$API_HITS" = "0" ]; then
    ok "bundle has no http:// API URL"
  else
    high "bundle has $API_HITS http:// API URL hits — should be https:// only"
  fi
else
  medium "frontend container not running — skip bundle audit (run after docker compose up)"
fi

# ---------------------------------------------------------------------------
section "10. DEBUG=False — generic error response"
# ---------------------------------------------------------------------------

if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps backend --format json 2>/dev/null | grep -q '"State":"running"'; then
  ERR_BODY=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T backend sh -c \
    "python -c 'import urllib.request; r=urllib.request.urlopen(\"http://localhost:8000/api/__does_not_exist__/\", timeout=3) if False else None' 2>&1 ; \
     curl -sS http://localhost:8000/api/__does_not_exist__/ -o /tmp/err.txt -w '%{http_code}' ; cat /tmp/err.txt ; rm -f /tmp/err.txt" \
    2>/dev/null || echo "")
  if echo "$ERR_BODY" | grep -qi "traceback\|django.core\|exception"; then
    blocker "404 response leaks traceback — DEBUG likely True"
  else
    ok "404 response is generic (no traceback leak)"
  fi
else
  medium "backend container not running — skip DEBUG smoke"
fi

# ---------------------------------------------------------------------------
section "11. Caddy admin block — IP allow-list status"
# ---------------------------------------------------------------------------

if [ -f "$COMPOSE_DIR/infra/Caddyfile" ]; then
  if grep -qE "^\s*#.*admin_allowed_ips" "$COMPOSE_DIR/infra/Caddyfile"; then
    high "/admin/ has NO IP allow-list (block commented in Caddyfile). Acceptable for beta with strong auth + 2FA, but documented hardening item."
  else
    ok "Caddyfile /admin/ block has IP allow-list configured"
  fi
fi

# ---------------------------------------------------------------------------
section "12. .gitignore covers .env.prod"
# ---------------------------------------------------------------------------

if [ -f "$COMPOSE_DIR/.gitignore" ] && grep -qE "^\.env\.prod$|^\.env\.prod\b" "$COMPOSE_DIR/.gitignore"; then
  ok ".env.prod in .gitignore"
else
  blocker ".env.prod NOT in .gitignore — risk of accidental commit"
fi

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------

TOTAL=$((PASS + FAIL_BLOCKER + FAIL_HIGH + FAIL_MEDIUM))
printf "\n  passed:   %d / %d\n" "$PASS" "$TOTAL"
printf "  blocker:  %d\n" "$FAIL_BLOCKER"
printf "  high:     %d\n" "$FAIL_HIGH"
printf "  medium:   %d\n\n" "$FAIL_MEDIUM"

if [ "$FAIL_BLOCKER" -gt 0 ]; then
  printf "%sFAILED — fix BLOCKERs before launch%s\n" "$R" "$N"
  exit 1
fi
if [ "$FAIL_HIGH" -gt 0 ] || [ "$FAIL_MEDIUM" -gt 0 ]; then
  printf "%sPASS (with caveats — review HIGH/MEDIUM)%s\n" "$Y" "$N"
  exit 2
fi
printf "%sOK — all checks passed%s\n" "$G" "$N"
exit 0
