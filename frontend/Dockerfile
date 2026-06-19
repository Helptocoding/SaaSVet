# syntax=docker/dockerfile:1.7
# Capa 1 (DEPLOY_VPS_PLAN.md): frontend image.
# Builder: node:20-alpine + pnpm → vite build.
# Runtime: nginx:alpine serving /dist on :80 (internal). Caddy proxies
# from :443 outside.

# ---- builder ----
FROM node:20-alpine AS builder
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

# P1-5 A4: credenciales de upload de source maps. SECRETO build-time — en CI
# pasarlas idealmente con BuildKit `--secret`. Se consumen solo durante
# `pnpm run build`; este stage builder se descarta, así que NO llegan al image
# runtime (nginx). Si están vacías, el plugin no se carga (ver vite.config.js).
ARG SENTRY_AUTH_TOKEN
ARG SENTRY_ORG
ARG SENTRY_PROJECT

# Copy source AFTER deps install to leverage layer cache.
COPY . .

# P1-5 A4: build con source maps 'hidden' (vite.config.js). El plugin de Sentry
# los sube y borra; el `find ... -delete` es safeguard por si el upload no corrió
# (sin token) → garantiza que ningún .map llegue a nginx (no exponer el código).
RUN SENTRY_AUTH_TOKEN=${SENTRY_AUTH_TOKEN} \
    SENTRY_ORG=${SENTRY_ORG} \
    SENTRY_PROJECT=${SENTRY_PROJECT} \
    pnpm run build \
 && find dist -name '*.map' -delete

# ---- runtime ----
FROM nginx:1.27-alpine AS runtime

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
