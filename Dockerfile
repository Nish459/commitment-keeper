# Stage 1: build the web UI. The output is plain static files, so it always builds natively
# (fast) even when the image targets another CPU, e.g. amd64 from an ARM Mac.
FROM --platform=$BUILDPLATFORM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: the API, serving the built UI from the same process.
FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    KEPT_WEB_DIR=/app/frontend/dist \
    KEPT_DB_PATH=/data/kept.db
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .
COPY --from=web /web/dist ./frontend/dist

# Run as an unprivileged user; /data is where a persistent (non-demo) install keeps its database.
RUN useradd --create-home --uid 10001 kept && mkdir /data && chown kept /data
USER kept

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# --proxy-headers makes rate limits see the real visitor address behind a platform proxy.
# Set FORWARDED_ALLOW_IPS to the proxy's address, or "*" only if the platform strips any
# client-supplied X-Forwarded-For header.
CMD ["uvicorn", "kept.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
