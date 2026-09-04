# Backend image: Python + FFmpeg + yt-dlp. Used by Render, Fly, Railway, or any VPS.
FROM python:3.12-slim-bookworm

# FFmpeg is required for MP3 conversion and merging video + audio streams.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

ENV PATH="/app/.venv/bin:$PATH" \
    DM_ENVIRONMENT=production \
    DM_DOWNLOAD_DIR=/data/downloads

RUN useradd -m appuser && mkdir -p /data/downloads && chown -R appuser /data /app
USER appuser

EXPOSE 8000
# Render and most PaaS inject $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
