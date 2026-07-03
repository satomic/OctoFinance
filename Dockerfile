# syntax=docker/dockerfile:1
#
# OctoFinance — GitHub Copilot AI FinOps Platform
#
# Multi-stage build:
#   1. frontend — build the React SPA with Node
#   2. cli      — download & checksum-verify the standalone GitHub Copilot CLI binary
#   3. runtime  — slim Python image with backend + frontend dist + Copilot CLI
#
# Notes:
#   * The Copilot Python SDK (>=1.0.5) is a pure-Python wheel; the Copilot CLI
#     is baked into the image and pointed to via COPILOT_CLI_PATH so the SDK
#     never needs to auto-download it at runtime.
#   * The CLI binary is a self-contained executable — no Node.js is needed at runtime.

############################
# Stage 1: frontend build
############################
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

############################
# Stage 2: Copilot CLI download (checksum-verified)
############################
FROM debian:bookworm-slim AS cli
ARG TARGETARCH
# Must speak the same SDK protocol as github-copilot-sdk (1.0.5 → protocol v3)
ARG COPILOT_CLI_VERSION=1.0.68
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) asset="copilot-linux-x64.tar.gz" ;; \
        arm64) asset="copilot-linux-arm64.tar.gz" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    base="https://github.com/github/copilot-cli/releases/download/v${COPILOT_CLI_VERSION}"; \
    curl -fsSL -o "/tmp/${asset}" "${base}/${asset}"; \
    curl -fsSL -o /tmp/SHA256SUMS.txt "${base}/SHA256SUMS.txt"; \
    cd /tmp && grep " ${asset}\$" SHA256SUMS.txt | sha256sum -c -; \
    mkdir -p /opt/copilot; \
    tar -xzf "/tmp/${asset}" -C /opt/copilot; \
    chmod +x /opt/copilot/copilot; \
    /opt/copilot/copilot --version

############################
# Stage 3: runtime
############################
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COPILOT_CLI_PATH=/usr/local/bin/copilot

WORKDIR /app

# Install Python dependencies (github-copilot-sdk >=1.0 ships a pure-Python wheel)
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Copilot CLI (standalone binary, no Node.js required)
COPY --from=cli /opt/copilot/copilot /usr/local/bin/copilot

# Application code + built frontend
COPY backend/ /app/backend/
COPY --from=frontend /build/dist /app/frontend/dist/

# Non-root user; /app/data holds all runtime state (PATs, auth, synced data, sessions)
RUN useradd --create-home --uid 1000 octofinance \
    && mkdir -p /app/data \
    && chown -R octofinance:octofinance /app

USER octofinance
VOLUME ["/app/data"]
EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
