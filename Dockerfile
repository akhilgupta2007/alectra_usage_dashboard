FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && \
    playwright install --with-deps chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

COPY . .

# Create directory for mounting data
RUN mkdir -p /app/data

EXPOSE 8000

ENV DATABASE_PATH=/app/data/green_button.db

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
