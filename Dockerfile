# syntax=docker/dockerfile:1
#
# Proposal AI Backend — container image.
#
# Two stages:
#   builder  — compiles/downloads all Python wheels into a self-contained venv
#   runtime  — slim image with only the *runtime* native libraries + that venv
#
# Native dependencies are not optional here (see requirements.txt comments):
#   pypandoc   -> needs the `pandoc` binary
#   weasyprint -> needs Pango / Cairo / GDK-PixBuf / libffi + real fonts
#   paddlex[ocr] -> pulls opencv-contrib-python, which needs libGL + glib
#   paddlepaddle -> needs libgomp (OpenMP)

# ---------------------------------------------------------------- builder ---
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0 \
    PYTHONDONTWRITEBYTECODE=1

# Build toolchain only — none of this survives into the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./

# BuildKit cache mount: re-builds after a requirements.txt tweak reuse the
# already-downloaded wheels instead of pulling ~2GB of paddle again.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# ---------------------------------------------------------------- runtime ---
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/app \
    # PaddleX caches its downloaded OCR/layout models here. Mounted as a volume
    # in docker-compose so the ~1GB first-run download survives restarts.
    PADDLE_PDX_CACHE_HOME=/home/app/.paddlex

RUN apt-get update && apt-get install -y --no-install-recommends \
        # --- pypandoc (DOCX export) ---
        pandoc \
        # --- weasyprint (PDF export) ---
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        shared-mime-info \
        fonts-dejavu-core \
        fonts-liberation \
        # --- opencv-contrib-python (via paddlex[ocr]) ---
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        # --- paddlepaddle (OpenMP) ---
        libgomp1 \
        # --- healthcheck ---
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Strip CRLF in case the file was checked out on Windows — a \r in the shebang
# line makes the container fail with a confusing "no such file or directory".
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

COPY . .

RUN mkdir -p /home/app/.paddlex /app/storage \
    && chown -R app:app /home/app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/ || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
