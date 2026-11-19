FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.lock ./backend/requirements.lock
RUN pip install --require-hashes -r backend/requirements.lock \
    && useradd --create-home --uid 10001 uptimex
COPY --chown=uptimex:uptimex alembic.ini ./
COPY --chown=uptimex:uptimex backend/app ./backend/app
COPY --chown=uptimex:uptimex backend/migrations ./backend/migrations
RUN mkdir -p /app/.local && chown -R uptimex:uptimex /app/.local
USER uptimex
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
