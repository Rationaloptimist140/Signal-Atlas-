FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 atlas && chown -R atlas /app
USER atlas

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)" || exit 1
# Migrations run before the server starts; they are idempotent, and a failed migration stops the release.
# --host "" listens on IPv4 and IPv6: Railway's private network can be IPv6-only.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host '' --port ${PORT:-8000}"]
