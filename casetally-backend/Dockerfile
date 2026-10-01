FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# CPU-only torch, installed BEFORE requirements.txt on purpose.
#
# sentence-transformers depends on torch. If it resolves torch itself it takes
# the default PyPI wheel, which on x86_64 drags in the whole CUDA stack: the
# nvidia-* runtime wheels, triton, and a CUDA-linked torch. That was 3.4GB of
# libraries in an image that has no GPU to use them.
#
# --index-url rather than --extra-index-url is deliberate. With an extra index
# pip sees both and may still pick the default build; with the index replaced
# there is only one candidate, so this is correct on every architecture rather
# than only on arm64, where the default wheel happens to be CPU-only anyway.
#
# Installing it first means the later `-r requirements.txt` finds the
# dependency already satisfied and leaves it alone.
RUN pip install --no-cache-dir torch==2.5.1 \
      --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image.
#
# SentenceTransformer(name) downloads from HuggingFace when the model is not
# cached, so without this every new pod would need working egress to an
# external service before it could answer its first query. Baking it in turns a
# runtime network dependency into a build-time one, and lets the deployment run
# with HF_HUB_OFFLINE=1.
#
# HF_HOME must be set before the download so the files land where the runtime
# will look for them, and it is world-readable so the image still works if it
# is later run as a non-root user.
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    chmod -R a+rX /opt/hf

COPY app ./app

EXPOSE 3001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001"]
