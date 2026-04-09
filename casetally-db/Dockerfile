# Use official pgvector image as base
FROM ankane/pgvector:latest

# Install Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Create virtual environment and install dependencies
COPY requirements.txt .
RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --no-cache-dir -r requirements.txt

# Add venv to PATH so alembic command works
ENV PATH="/app/venv/bin:$PATH"

# Copy Alembic config and migrations
COPY alembic.ini .
COPY alembic/ ./alembic/

# Copy Python package files (needed for Alembic to import models)
COPY __init__.py .
COPY models.py .

# Copy init.sql to Docker's auto-init location
COPY init.sql /docker-entrypoint-initdb.d/01-init.sql

# Expose Postgres port
EXPOSE 5432

# Default command: run Postgres (inherits from base image)
CMD ["postgres"]