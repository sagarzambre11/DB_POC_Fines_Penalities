# ---------------------------------------------------------------------------
# Dockerfile — Regulatory Enforcement Intelligence PoC
# ---------------------------------------------------------------------------
# Build:  docker build -t reg-enforcement-poc .
# Run:    docker run -p 8501:8501 --env-file .env reg-enforcement-poc
# ---------------------------------------------------------------------------

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required by pdfplumber / Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest first (layer cache optimisation)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose Streamlit default port
EXPOSE 8501

# Streamlit runtime configuration
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entry point
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
