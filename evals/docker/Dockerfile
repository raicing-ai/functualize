# Eval sandbox: everything an agent needs to build and run a functualize app,
# and nothing else. Built once, reused across runs.
#
#   cd evals && npm run image
#
# The container is not a security boundary against a determined attacker — it
# is a blast radius limiter for a *confused* agent running with
# bypassPermissions. It stops the two things that actually go wrong: edits
# escaping into the real checkout, and writes landing in the operator's $HOME.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# uv, in a location every user can reach — the container runs as the caller's
# uid under docker, so nothing may live in a per-user directory.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# The agent's HOME. World-writable because `docker run --user` gives us an
# arbitrary uid with no passwd entry.
RUN mkdir -p /tmp/agent /work /src \
    && chmod 1777 /tmp/agent

# Cache locations inside the image. These are per-container and die with it:
# every run is `--rm`. The *shared* cache is a host volume the harness mounts
# over UV_CACHE_DIR (see `uv_cache_dir()` in providers/_harness.py), which is
# what actually stops 78 runs re-downloading the world.
ENV UV_CACHE_DIR=/tmp/agent/uv \
    UV_LINK_MODE=copy \
    XDG_CACHE_HOME=/tmp/agent/cache \
    XDG_CONFIG_HOME=/tmp/agent/config \
    XDG_DATA_HOME=/tmp/agent/data \
    HOME=/tmp/agent

WORKDIR /work
