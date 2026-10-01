# workers/embedding-worker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip --disable-pip-version-check

# CPU-only torch, installed BEFORE requirements.txt.
#
# Identical version and index to casetally-backend, so the vectors this worker
# writes and the query vectors the API encodes come from the same torch build.
# A mismatch there would mean stored and query embeddings were produced by
# different numeric kernels, which is a silent accuracy problem rather than a
# visible failure.
#
# --index-url rather than --extra-index-url so the CPU wheel is the only
# candidate on every architecture, not just on arm64 where the default wheel
# happens to be CPU-only.
RUN pip install --no-cache-dir torch==2.5.1 \
      --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install with optimizations
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --disable-pip-version-check \
    --timeout=120 \
    -r requirements.txt

# Bake the embedding model into the image, matching casetally-backend.
#
# Without this every new worker pod downloads ~90MB from HuggingFace before it
# can encode anything, which makes pod startup depend on an external service.
# Baking it in lets the deployment run with HF_HUB_OFFLINE=1.
#
# This must happen BEFORE the USER switch below, because the download needs to
# write to /opt/hf. a+rX afterwards so the unprivileged worker user can read it.
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    chmod -R a+rX /opt/hf

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
