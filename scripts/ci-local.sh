#!/usr/bin/env bash
# P1-3 — Local mirror of the main steps in .github/workflows/ci.yml.
# Run this before pushing to catch what CI would catch ("passes on my machine"
# parity). Requires: Python 3.13 + a reachable PostgreSQL, Node 20 + pnpm 9.
#
# Out of scope (run separately if needed): gitleaks / pip-audit / pnpm audit
# (the security job), deployment, Docker, coverage. See ADR / P1-3 plan.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- CI-equivalent env (dummy, NON-secret) ---------------------------------
# SECRET_KEY has no default in settings.py; ENVIRONMENT=dev avoids the
# production Redis requirement (LocMem fallback, ADR p41).
export SECRET_KEY="${SECRET_KEY:-ci-local-not-secret}"
export ENVIRONMENT="${ENVIRONMENT:-dev}"
export DEBUG="${DEBUG:-False}"
export DATABASE_URL="${DATABASE_URL:-postgres://postgres:postgres@localhost:5432/test_db}"

echo "== backend =="
cd "$ROOT/backend"
pip install -r requirements.lock
python manage.py makemigrations --check --dry-run
python manage.py migrate --no-input
python manage.py test --parallel

echo "== frontend =="
cd "$ROOT/frontend"
pnpm install --frozen-lockfile
pnpm run build
pnpm run smoke:urls

echo "== ci-local OK =="
