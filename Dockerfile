# Build for Rahti with: docker buildx build --platform linux/amd64 --load -t recruitifi:local .
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
FROM ${NODE_IMAGE} AS frontend-build
ARG PNPM_VERSION=10.28.0
WORKDIR /build/frontend
RUN npm install --global pnpm@${PNPM_VERSION}
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
ENV VITE_API_URL=""
RUN pnpm build

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    TALENTMATCH_SERVE_FRONTEND=1 \
    TALENTMATCH_DB=/var/data/talentmatch.sqlite3 \
    PORT=8080
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
COPY deploy/rahti/requirements.lock /app/backend/requirements.lock
RUN python -m pip install --no-cache-dir -r /app/backend/requirements.txt -c /app/backend/requirements.lock
COPY backend/*.py backend/schema.sql /app/backend/
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
# Source and packages only need to be readable. Writes belong to PVC or /tmp.
# A PVC hides these image permissions: the SCC/CSI fsGroup must grant PVC access.
RUN chmod -R a+rX,go-w /app \
    && mkdir -p /var/data \
    && chgrp 0 /var/data \
    && chmod 2770 /var/data
# No fixed USER: Rahti supplies the arbitrary UID and groups. The launcher refuses root.
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["python", "-m", "backend.container_start"]
