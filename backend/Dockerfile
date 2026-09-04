# Backend image: Python + FFmpeg + yt-dlp. Used by Render, Fly, Railway, or any VPS.
#
#   docker build -t dm-api ./backend
#   docker run --rm -p 8000:8000 -e PORT=8000 dm-api
#
# Two stages: the builder resolves and installs dependencies, the runtime stage
# gets only the finished virtualenv. That keeps the uv binaries, the wheel cache
# and the lock metadata out of the published image.

# --------------------------------------------------------------- builder ---
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

# UV_PYTHON_DOWNLOADS=never keeps uv on this image's own interpreter, so the
# venv we copy forward points at /usr/local/bin/python, which exists in the
# runtime stage too. Downloading a second interpreter would break that.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies change far less often than application code, so they get their
# own layer: editing app/ does not reinstall yt-dlp and friends.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# --------------------------------------------------------------- runtime ---
FROM python:3.12-slim-bookworm

# FFmpeg is required for MP3 conversion and for merging video + audio streams.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Fixed uid/gid so a mounted volume keeps predictable ownership across rebuilds.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home appuser \
    && mkdir -p /data/downloads \
    && chown -R appuser:appuser /data

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app

# /app stays root-owned and read-only to appuser: the process can run the code
# but cannot rewrite it. Everything that needs writing lives under /data.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/appuser \
    DM_ENVIRONMENT=production \
    DM_DOWNLOAD_DIR=/data/downloads \
    DM_DATABASE_URL=sqlite:////data/dm.db

USER appuser
EXPOSE 8000

# Render and most PaaS inject $PORT.
#   exec           -> uvicorn becomes PID 1, so SIGTERM reaches it and the
#                     lifespan shutdown (drain workers, dispose the engine) runs.
#   --proxy-headers -> read X-Forwarded-For, but only from the addresses in
#                     $FORWARDED_ALLOW_IPS (uvicorn's default is 127.0.0.1).
#                     Set FORWARDED_ALLOW_IPS=* on Render, where the container
#                     is only reachable through Render's load balancer; without
#                     it every request looks like it came from the balancer and
#                     the per-IP rate limit becomes one global limit.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
