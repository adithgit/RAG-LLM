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

# Install heavy ML packages first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip3 install --no-cache-dir torch==2.2.1 transformers==4.41.2 accelerate \
    llama-index>=0.10.15 llama-index-llms-huggingface>=0.1.4 \
    llama-index-embeddings-huggingface>=0.1.4 chromadb==0.4.24 \
    llama-index-vector-stores-chroma>=0.1.4 PyMuPDF>=1.23.26 \
    langchain-community>=0.0.24 sentencepiece>=0.2.0 sentence-transformers

# Install lightweight app packages (changes more often - separate layer)
COPY requirements-app.txt .
RUN pip3 install --no-cache-dir -r requirements-app.txt

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
