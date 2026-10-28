# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MCR_DATA_DIR=/tmp/mcr-data MCR_LOG_FORMAT=json PORT=8000
WORKDIR /app
COPY requirements.txt requirements-azure.txt ./
RUN pip install -r requirements.txt -r requirements-azure.txt
COPY match_insights ./match_insights
COPY web ./web
COPY docs/validation.json ./docs/validation.json
RUN useradd --uid 10001 --create-home app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/api/health')"
CMD ["sh", "-c", "uvicorn match_insights.server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --timeout-keep-alive 75"]
