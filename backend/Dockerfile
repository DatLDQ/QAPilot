FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    QAPILOT_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
# Chromium and its system libraries come from the same Playwright release as the pip package,
# so the explore session and the replayed suites always drive the same browser build.
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app

RUN useradd --create-home --uid 1000 qapilot && mkdir -p /data && chown qapilot /data
USER qapilot
VOLUME ["/data"]
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/api/health')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
