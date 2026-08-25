# Keep the API image independent from the host Python installation so the
# checkout and its lock file remain the complete migration unit.
FROM python:3.11-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV UV_INDEX_URL=${PIP_INDEX_URL}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Run the API as an unprivileged account; the host-mounted runtime directory is
# prepared with the same UID during deployment so uploads and SQLite remain writable.
RUN groupadd --system --gid 10001 bhzd \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home bhzd

# uv resolves the exact server/uv.lock graph while the build cache still
# invalidates cleanly when dependency metadata changes.
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==0.8.17"
COPY server/pyproject.toml server/uv.lock /app/server/
# Re-resolve the lock inside the image so a regional mirror can provide the
# same version graph without retaining direct files.pythonhosted.org URLs.
RUN cd /app/server && uv lock --index-url "${PIP_INDEX_URL}" \
    && uv sync --locked --no-dev

# Runtime code and read-only teaching assets are copied into the image. The
# compose file mounts /app/var separately so SQLite and uploads survive rebuilds.
COPY server /app/server
COPY data /app/data
COPY docs /app/docs
RUN mkdir -p /app/var \
    && chown -R 10001:10001 /app/server /app/data /app/docs /app/var

ENV BHZD_HOST=0.0.0.0 \
    BHZD_PORT=8787 \
    BHZD_DATA_DIR=/app/data \
    BHZD_UPLOAD_DIR=/app/var/uploads \
    BHZD_DATABASE_PATH=/app/var/bhzd.sqlite \
    BHZD_MAIL_OUTBOX_PATH=/app/var/mail_outbox.log

# The Python package lives under /app/server; keep runtime imports and relative
# migration/resource lookups anchored to that application root.
WORKDIR /app/server

EXPOSE 8787

# The health endpoint is intentionally checked inside the container network;
# Nginx remains the only public application entry point.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)"

USER 10001:10001

CMD ["/app/server/.venv/bin/python", "-m", "bhzd_py.main"]
