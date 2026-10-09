# Hugging Face Space image: builds Kept from the public GitHub repo, always in demo mode.
# Rebuild after pushing new code by restarting the Space (Settings -> Factory reboot).

FROM alpine:3.20 AS src
ARG REPO_URL=https://github.com/Nish459/commitment-keeper.git
ARG REPO_REF=master
RUN apk add --no-cache git
RUN git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" /src

FROM --platform=$BUILDPLATFORM node:24-slim AS web
WORKDIR /web
COPY --from=src /src/frontend/package.json /src/frontend/package-lock.json ./
RUN npm ci
COPY --from=src /src/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    KEPT_WEB_DIR=/app/frontend/dist \
    KEPT_DEMO_MODE=true
WORKDIR /app
COPY --from=src /src/pyproject.toml /src/README.md /src/LICENSE ./
COPY --from=src /src/src ./src
RUN pip install .
COPY --from=web /web/dist ./frontend/dist

# Hugging Face runs Spaces as user 1000.
RUN useradd --create-home --uid 1000 user
USER user

EXPOSE 8000
CMD ["uvicorn", "kept.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
