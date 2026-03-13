FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Node.js for mini-app build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt_tab'); nltk.download('stopwords')"

# Copy application code
COPY . .

# Build the mini-app frontend (--production=false ensures devDeps like vite/typescript)
RUN cd mini-app && npm install --production=false --no-audit --no-fund && (npm run build || ./node_modules/.bin/vite build) && ls -la dist/ && cd ..

# Create data and logs directories
RUN mkdir -p data logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=10000

# CRITICAL: Single instance for Telegram polling bots
ENV WEB_CONCURRENCY=1

# Expose the web service port
EXPOSE 10000

# Health check — increased start-period for Telegram grace period
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:10000/health || exit 1

# Use exec form so SIGTERM goes directly to the Python process
# (not to a shell wrapper that would swallow the signal)
# start.sh will build mini-app if needed, then exec python main.py
CMD ["bash", "start.sh"]
