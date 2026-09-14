FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/reader.db

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --system --uid 10001 reader \
    && mkdir -p /data \
    && chown reader /data
USER reader
VOLUME ["/data"]

EXPOSE 8651
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8651/healthz', timeout=4)"

# One process: the background feed refresher must not run in several workers.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8651", "--proxy-headers", "--forwarded-allow-ips", "*"]
