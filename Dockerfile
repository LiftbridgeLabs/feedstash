# Pinned to an exact image, like requirements.txt; Dependabot proposes updates.
FROM python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="FeedStash" \
      org.opencontainers.image.description="Self-hosted feed reader and read-it-later stash" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV FEEDSTASH_VERSION=${VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_PATH=/data/feedstash.db \
    HOST=0.0.0.0 \
    PORT=8672 \
    FORWARDED_ALLOW_IPS=* \
    PUID=1000 \
    PGID=1000

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY app ./app
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8672
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8672'), timeout=4)"

# The entrypoint starts as root only to fix the data folder's owner, then runs the app as PUID:PGID.
# One process: the background feed refresher must not run in several workers.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "app"]
