# Use NVIDIA CUDA base image for GPU inference
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Set noninteractive installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install requirements (all pinned - fast resolver, no backtracking)
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Expose port
EXPOSE 5000

# Set environment variables for huggingface and app paths
ENV DATA_DIR=/app/data
ENV CHROMA_DB_PATH=/app/chroma_db
ENV HUGGINGFACE_HUB_CACHE=/app/model_cache
ENV HF_HOME=/app/model_cache

# Run the app with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "900", "--workers", "1", "app:app"]
