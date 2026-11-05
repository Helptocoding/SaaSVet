# syntax=docker/dockerfile:1.7
# Capa 1 (DEPLOY_VPS_PLAN.md): frontend image.
# Builder: node:20-alpine + pnpm → vite build.
# Runtime: nginx:alpine serving /dist on :80 (internal). Caddy proxies
# from :443 outside.

# ---- builder ----
# Pinned by digest, keeping the tag readable. To bump: read the new index digest from
# the registry, review the release, and let the CI images job build it.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder
WORKDIR /app

# Pin pnpm to match pnpm-lock.yaml lockfileVersion (frontend/package.json
# does not pin packageManager; bump here if you upgrade pnpm).
RUN npm install -g pnpm@9

# Install deps first so changes in src/ don't bust the deps layer cache.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build-time public env vars. These get baked INTO the bundle — anything
# put here is visible to anyone who downloads the JS. Pass only public
# values (API URL, Sentry DSN are designed to be public).
ARG VITE_API_URL
ARG VITE_SENTRY_DSN
# P1-5 A4/A5: environment + release (públicos) para los tags de Sentry browser.
ARG VITE_SENTRY_ENVIRONMENT
ARG VITE_SENTRY_RELEASE
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_SENTRY_DSN=${VITE_SENTRY_DSN} \
    VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT} \
    VITE_SENTRY_RELEASE=${VITE_SENTRY_RELEASE}

# P1-5 A4: destino de la subida de source maps; no son secretos. El token va por
# BuildKit `--secret` (abajo), nunca como ARG: un build arg queda en el historial
# de la etapa y en la caché del host que construye, aunque no llegue a nginx.
# Sin token, sin org o sin proyecto el plugin no se carga (ver vite.config.js).
ARG SENTRY_ORG
ARG SENTRY_PROJECT

# Copy source AFTER deps install to leverage layer cache.
COPY . .

# P1-5 A4: build con source maps 'hidden' (vite.config.js). El plugin de Sentry
# los sube y borra; el `find ... -delete` es safeguard por si el upload no corrió
# (sin token) → garantiza que ningún .map llegue a nginx (no exponer el código).
# El secreto solo existe durante este RUN: no entra en capas, historial ni caché.
RUN --mount=type=secret,id=sentry_auth_token \
    SENTRY_AUTH_TOKEN="$(cat /run/secrets/sentry_auth_token 2>/dev/null || true)"; \
    export SENTRY_AUTH_TOKEN; \
    if [ -n "$SENTRY_AUTH_TOKEN" ]; then echo "[build] sentry token: provided"; else echo "[build] sentry token: absent"; fi; \
    SENTRY_ORG=${SENTRY_ORG} \
    SENTRY_PROJECT=${SENTRY_PROJECT} \
    pnpm run build \
 && find dist -name '*.map' -delete

# ---- runtime ----
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10 AS runtime

# Replace the default vhost; ours is single-purpose (SPA static + fallback).
RUN rm -rf /usr/share/nginx/html/* /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf

# nginx:alpine already runs the master as root then drops worker to
# nginx user. PID 1 must stay root to bind :80; this is the standard
# pattern and accepted in single-purpose containers.

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost/ || exit 1
