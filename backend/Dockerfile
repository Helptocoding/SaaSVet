# syntax=docker/dockerfile:1.7
# Capa 1 (DEPLOY_VPS_PLAN.md): backend image.
# Multi-stage: builder compiles wheels, runtime is slim + non-root.

# Pinned by digest, keeping the tag readable. To bump: read the new index digest from
# the registry, review the release, and let the CI images job build it.
FROM python:3.13-slim@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# ---- builder ----
# build-essential covers any pure-source wheel; libpq5 not needed because
# psycopg[binary] ships its own libpq.so inside the wheel.
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.lock .
RUN pip wheel --wheel-dir=/wheels -r requirements.lock

# ---- runtime ----
# curl is only here for the Docker healthcheck and external smoke tests.
# Drop it later if you wire healthcheck via `python -c "urllib.request..."`
# instead (already done in compose). For now keep — debug-friendly.
FROM base AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system app \
 && useradd  --system --gid app --home-dir /app --shell /sbin/nologin app

WORKDIR /app

# Install from pre-built wheels — no network, no compilers.
COPY --from=builder /wheels /wheels
COPY requirements.lock .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock \
 && rm -rf /wheels

# Copy source last so changes don't bust the dependency layer cache.
COPY --chown=app:app . /app

# Ensure script is executable inside container — .gitattributes guarantees
# LF endings; the +x bit may not survive every checkout / tarball, so chmod
# defensively. staticfiles/ may not exist yet — create it.
RUN chmod 755 /app/scripts/release.sh \
 && mkdir -p /app/staticfiles \
 && chown -R app:app /app

USER app
EXPOSE 8000

# Sensible default; compose overrides with explicit flags (workers, timeout).
CMD ["gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000"]
