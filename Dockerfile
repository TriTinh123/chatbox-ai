# ─────────────────────────────────────────────────────────────────────────────
#  Revenue AI — Dockerfile
#  Base image: Python 3.12 slim (required by Django 6.x)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build-time secret — only used for `collectstatic`, never baked into the image
# Override at build time:  docker build --build-arg SECRET_KEY=dummy ...
ARG SECRET_KEY=build-time-dummy-key-not-used-at-runtime

WORKDIR /app

# Install system dependencies needed by pandas / Pillow / psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user early so we can set correct ownership
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Install Python dependencies first (leverages Docker layer cache)
COPY requirements/ requirements/
RUN pip install --upgrade pip \
    && pip install -r requirements/production.txt

# Copy project source with correct ownership
COPY --chown=appuser:appgroup . .

# Create required runtime directories
RUN mkdir -p logs media staticfiles \
    && chown -R appuser:appgroup logs media staticfiles

# Collect static files (uses the build-arg SECRET_KEY — safe, not a real key)
RUN SECRET_KEY=${SECRET_KEY} python manage.py collectstatic --noinput --settings=config.settings.production

USER appuser

EXPOSE 8000

# Gunicorn config is read from gunicorn.conf.py
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]

