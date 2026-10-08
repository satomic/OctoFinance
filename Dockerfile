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
#   * The Copilot Python SDK is a pure-Python wheel; the Copilot CLI
#     is baked into the image and pointed to via COPILOT_CLI_PATH so the SDK
#     never needs to auto-download it at runtime.
#   * Both the Copilot CLI and the Copilot Python SDK default to their latest
#     release at build time (same as Dockerfile-go). Pin either for a
#     reproducible build or a rollback:
#       --build-arg COPILOT_CLI_VERSION=1.0.93 --build-arg COPILOT_SDK_VERSION=1.0.17
#   * The CLI binary is a self-contained executable — no Node.js is needed at runtime.
#   * The frontend and cli stages run on the build host's platform ($BUILDPLATFORM):
#     their output (static files / a downloaded binary picked by TARGETARCH) does
#     not depend on the CPU they run on. Running them under QEMU for arm64 is
#     slow, and `npm ci` can hang there indefinitely.

############################
# Stage 1: frontend build
############################
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

############################
# Stage 2: Copilot CLI download (checksum-verified)
############################
# alpine ships wget with HTTPS, sha256sum, tar and the CA bundle, so this stage
# installs no packages and needs no distro package mirror.
FROM --platform=$BUILDPLATFORM alpine:3.22 AS cli
ARG TARGETARCH
# "latest" (default) or a release such as 1.0.93. Must speak the Copilot Python
# SDK's protocol version (protocol v3 for SDK 1.0.x). "latest" is resolved through
# the /releases/latest redirect to /releases/tag/v<version>; the checksum is
# verified against that release's SHA256SUMS.txt for every architecture.
ARG COPILOT_CLI_VERSION=latest
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) asset="copilot-linux-x64.tar.gz" ;; \
        arm64) asset="copilot-linux-arm64.tar.gz" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    fetch() { for i in 1 2 3 4 5; do wget -q -O "$2" "$1" && return 0; sleep 3; done; return 1; }; \
    version="${COPILOT_CLI_VERSION#v}"; \
    if [ "${version}" = "latest" ]; then \
        for i in 1 2 3 4 5; do \
            version="$(wget -q -S --spider https://github.com/github/copilot-cli/releases/latest 2>&1 \
                | sed -n 's#.*[Ll]ocation: .*/releases/tag/v\([^[:space:]]*\).*#\1#p' | tail -n 1)"; \
            [ -n "${version}" ] && break; sleep 3; \
        done; \
        [ -n "${version}" ]; \
    fi; \
    echo "Copilot CLI: ${version}"; \
    base="https://github.com/github/copilot-cli/releases/download/v${version}"; \
    fetch "${base}/${asset}" "/tmp/${asset}"; \
    fetch "${base}/SHA256SUMS.txt" /tmp/SHA256SUMS.txt; \
    cd /tmp && grep " ${asset}\$" SHA256SUMS.txt | sha256sum -c -; \
    mkdir -p /opt/copilot; \
    tar -xzf "/tmp/${asset}" -C /opt/copilot; \
    chmod +x /opt/copilot/copilot

############################
# Stage 3: runtime
############################
FROM python:3.13-slim AS runtime
ARG TARGETARCH
ARG BUILDARCH
# "latest" (default) or a release such as 1.0.17 for the Copilot Python SDK
ARG COPILOT_SDK_VERSION=latest

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COPILOT_CLI_PATH=/usr/local/bin/copilot

WORKDIR /app

# Install Python dependencies (github-copilot-sdk >=1.0 ships a pure-Python wheel),
# then the requested Copilot Python SDK release (latest by default)
COPY backend/requirements.txt /tmp/requirements.txt
RUN set -eux; \
    pip install --no-cache-dir -r /tmp/requirements.txt; \
    if [ "${COPILOT_SDK_VERSION}" = "latest" ]; then \
        pip install --no-cache-dir --upgrade github-copilot-sdk; \
    else \
        pip install --no-cache-dir "github-copilot-sdk==${COPILOT_SDK_VERSION#v}"; \
    fi; \
    echo "Copilot Python SDK: $(pip show github-copilot-sdk | sed -n 's/^Version: //p')"; \
    rm -f /tmp/requirements.txt

# Copilot CLI (standalone binary, no Node.js required). Smoke test it here (it
# needs glibc), only for native builds where it runs without emulation.
COPY --from=cli /opt/copilot/copilot /usr/local/bin/copilot
RUN if [ "${TARGETARCH}" = "${BUILDARCH}" ]; then copilot --version; fi

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
