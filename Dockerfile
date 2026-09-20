FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    playwright install --with-deps chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

COPY . .

# Create directory for mounting data
RUN mkdir -p /app/data

EXPOSE 8000

ENV DATABASE_PATH=/app/data/green_button.db
# Restrict glibc memory arenas to prevent multi-threaded heap fragmentation
ENV MALLOC_ARENA_MAX=2
ENV PYTHONUNBUFFERED=1
ENV SCRAPER_DOWNLOAD_TIMEOUT_SECONDS=120

ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
