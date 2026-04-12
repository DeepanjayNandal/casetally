# workers/embedding-worker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install with optimizations
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --upgrade pip \
    --disable-pip-version-check \
    --timeout=120 \
    -r requirements.txt

# Copy application code
COPY embedding_worker.py .
COPY embedding_service.py .
COPY state_manager.py .
COPY shared/ ./shared/

# Create non-root user
RUN useradd -m -u 1000 worker && \
    chown -R worker:worker /app
USER worker

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import redis; r=redis.Redis(host='${REDIS_HOST:-redis}', port=${REDIS_PORT:-6379}); r.ping()" || exit 1

CMD ["python", "-u", "embedding_worker.py"]