#!/usr/bin/env bash
# P1-6B: shared helpers for deploy.sh + rollback.sh.
#
# SOURCED, never executed directly. Does NOT set -e (the caller owns shell
# options). Convention: ALL human-readable log goes to STDERR; the only thing a
# function prints to STDOUT is a machine value meant to be captured via $(...).
#
# Path resolution is location-based (parent of scripts/), so these helpers work
# regardless of where the repo is cloned (/home/deploy/apps, /opt/vet/app, …).
# No hard-coded server paths.

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$_LIB_DIR/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
STATE_FILE="${STATE_FILE:-$ROOT_DIR/.deploy-state}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/vet}"

LOG_TAG="${LOG_TAG:-deploy}"
log() { printf '[%s] %s\n' "$LOG_TAG" "$*" >&2; }
err() { printf '[%s][ERR] %s\n' "$LOG_TAG" "$*" >&2; }

# docker compose wrapper bound to the prod file + env. NEVER echoes env values.
compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

# Source .env.prod WITHOUT echoing it (no set -x in this path).
load_env() {
  [ -f "$ENV_FILE" ] || { err "env file not found: $ENV_FILE"; return 1; }
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}

# Short git SHA of the working tree (the deploy identifier + image tag).
current_sha() { git -C "$ROOT_DIR" rev-parse --short HEAD; }

# Idempotent KEY=VALUE upsert in .env.prod, preserving file perms (600).
# VALUE is alnum (SHA) in our use — no delimiter games needed, but we rebuild
# via awk so a value with '=' would still be safe.
set_env_var() {
  local key="$1" val="$2" tmp
  [ -f "$ENV_FILE" ] || { err "env file not found: $ENV_FILE"; return 1; }
  # Never write THROUGH a symlink: an attacker-planted link could redirect the
  # secrets file to a world-readable path.
  [ -L "$ENV_FILE" ] && { err "refusing to write through symlink: $ENV_FILE"; return 1; }
  if grep -qE "^${key}=" "$ENV_FILE"; then
    # Temp beside the target (same fs, deploy-owned dir) so the brief copy of the
    # secrets file never lands in a shared /tmp. mktemp creates it 0600.
    tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
    awk -v k="$key" -v v="$val" '
      BEGIN{FS="="}
      $1==k {print k"="v; next}
      {print}
    ' "$ENV_FILE" > "$tmp"
    cat "$tmp" > "$ENV_FILE"   # write back in place → keeps inode
    rm -f "$tmp"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
  # Re-assert 600: the upstream file should already be 600, but never let this
  # helper be the reason the secrets file widens.
  chmod 600 "$ENV_FILE" 2>/dev/null || true
}

# ---- deploy state (.deploy-state, 600) ------------------------------------
# Records which image tag is live, the one before it (rollback target) and the
# pre-deploy DB snapshot taken for the live deploy.
read_state() { [ -f "$STATE_FILE" ] && sed -n "s/^$1=//p" "$STATE_FILE" | head -1; }

write_state() { # current  previous  predeploy_backup_path
  ( umask 077
    cat > "$STATE_FILE" <<EOF
CURRENT_TAG=$1
PREVIOUS_TAG=$2
PREDEPLOY_BACKUP=$3
DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
  )
  chmod 600 "$STATE_FILE" 2>/dev/null || true
}

# ---- health gate ----------------------------------------------------------
# All checks are IN-CONTAINER (no DNS/TLS/hairpin dependency). Determinism over
# realism: if the containers are healthy and the backend reports the new SHA,
# the deploy is live. external_health() adds a warn-only public-path probe.

_service_health() { # service-name → prints health status or "missing"
  local cid; cid="$(compose ps -q "$1" 2>/dev/null)"
  [ -n "$cid" ] || { echo "missing"; return; }
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo "missing"
}

# NOTE: caddy is intentionally NOT in the blocking set. Its healthcheck can sit
# in `starting` while Let's Encrypt issues the first cert, which would falsely
# fail the gate and trigger a rollback of an otherwise-good backend. The edge
# (caddy/TLS/public path) is covered warn-only by external_health(). The app
# being healthy = postgres + redis + backend + frontend.
services_healthy() {
  local s st
  for s in postgres redis backend frontend; do
    st="$(_service_health "$s")"
    [ "$st" = "healthy" ] || { err "service $s not healthy (status=$st)"; return 1; }
  done
  return 0
}

# Prints "<commit>\t<version>" the running backend serves (either field may be
# empty). From a single /api/version/ request:
#   commit  = git SHA   (the deploy identifier — what we expect to match)
#   version = product version (APP_VERSION, e.g. 1.0.0-beta) — fallback only
# The API cleanly separates the two; the gate prefers commit and falls back to
# version (covers a backend whose APP_VERSION carries the SHA but commit unset).
#
# X-Forwarded-Proto: https — /api/version/ is NOT in SECURE_REDIRECT_EXEMPT, so
# with SECURE_SSL_REDIRECT=True a plain-HTTP loopback hit gets 301'd to https,
# which urlopen follows into gunicorn (plain HTTP, no TLS) → failure. The header
# makes Django treat the request as secure (SECURE_PROXY_SSL_HEADER) → no redirect.
backend_identity() {
  local cid; cid="$(compose ps -q backend 2>/dev/null)"
  [ -n "$cid" ] || { printf '\t'; return; }
  docker exec "$cid" python -c "import urllib.request,json;req=urllib.request.Request('http://localhost:8000/api/version/',headers={'X-Forwarded-Proto':'https'});d=json.load(urllib.request.urlopen(req,timeout=3));print((d.get('commit') or '')+'\t'+(d.get('version') or ''))" 2>/dev/null | tr -d '\r'
}

backend_readyz_ok() { # 0 if /api/readyz returns 200 (DB reachable)
  local cid; cid="$(compose ps -q backend 2>/dev/null)"
  [ -n "$cid" ] || return 1
  # X-Forwarded-Proto: https for parity with backend_identity. readyz IS in
  # SECURE_REDIRECT_EXEMPT today, so the header is belt-and-suspenders (keeps
  # working if readyz is ever dropped from the exempt list).
  docker exec "$cid" python -c "import urllib.request,sys;req=urllib.request.Request('http://localhost:8000/api/readyz/',headers={'X-Forwarded-Proto':'https'});r=urllib.request.urlopen(req,timeout=3);sys.exit(0 if r.status==200 else 1)" 2>/dev/null
}

# Poll until all services healthy + readyz ok + the running backend identifies
# as the expected SHA, or timeout. Returns 0 on success.
#
# Match precedence (the /api/version/ contract separates the two cleanly):
#   1. commit  == expected_sha   ← primary: commit is the git SHA, same kind
#   2. version == expected_sha   ← fallback: only passes if APP_VERSION literally
#                                  carries the SHA (commit unset). A real product
#                                  version like "1.0.0-beta" never equals a SHA,
#                                  so it cannot false-pass.
health_gate() { # expected_sha
  local sha="$1" timeout="${DEPLOY_HEALTH_TIMEOUT:-120}" waited=0 step=5 got commit version
  log "health gate: waiting for commit=$sha (timeout ${timeout}s)"
  while [ "$waited" -lt "$timeout" ]; do
    if services_healthy && backend_readyz_ok; then
      got="$(backend_identity)"
      commit="${got%%$'\t'*}"
      version="${got#*$'\t'}"
      if [ -n "$commit" ] && [ "$commit" = "$sha" ]; then
        log "health gate PASS (services healthy, readyz ok, commit=$sha)"
        return 0
      fi
      if [ "$version" = "$sha" ]; then
        log "health gate PASS (services healthy, readyz ok, version=$sha; commit unset/mismatch)"
        return 0
      fi
      log "identity mismatch: commit='${commit:-?}' version='${version:-?}' expected='$sha' (still settling)"
    fi
    sleep "$step"; waited=$((waited+step))
  done
  err "health gate FAILED after ${timeout}s"
  return 1
}

# Warn-only external probe through Caddy (validates TLS + full path). Never
# fails the deploy: DNS/hairpin/cert-issuance can make the host unable to curl
# its own public domain even when the stack is perfectly healthy.
external_health() {
  [ -n "${DOMAIN:-}" ] || return 0
  if curl -fsS -m 5 "https://$DOMAIN/api/healthz/" >/dev/null 2>&1; then
    log "external probe OK: https://$DOMAIN/api/healthz/"
  else
    err "WARN: external https://$DOMAIN/api/healthz/ probe failed (DNS/TLS/hairpin?) — internal gate already passed, not blocking."
  fi
}

# ---- image retention ------------------------------------------------------
# Best-effort: keep the newest N SHA-tagged images per repo, drop older ones.
# NEVER removes:
#   - 'latest'/'capa1' baselines,
#   - the CURRENT_TAG and PREVIOUS_TAG from .deploy-state (the rollback target
#     MUST survive pruning, or rollback fails with "image not on disk").
# Never fails the deploy; docker rmi refuses to remove an in-use image (ignored).
prune_images() {
  local keep="${1:-3}" repo cur prev
  cur="$(read_state CURRENT_TAG || true)"
  prev="$(read_state PREVIOUS_TAG || true)"
  for repo in vet-backend vet-frontend; do
    docker images "$repo" --format '{{.CreatedAt}}\t{{.Tag}}\t{{.ID}}' 2>/dev/null \
      | sort -r \
      | awk -F'\t' -v keep="$keep" -v cur="$cur" -v prev="$prev" '
          { tag=$2; id=$3 }
          tag=="latest" || tag=="capa1" || tag==cur || tag==prev { next }
          { c++; if (c > keep) print id }
        ' \
      | xargs -r docker rmi 2>/dev/null || true
  done
}
