# Multi-stage build for Code Architect Agent

# Stage 1: Python backend
FROM python:3.11-slim as backend

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ /app/src/

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# Default command
CMD ["python", "-m", "uvicorn", "architect.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Stage 2: Node.js frontend build
FROM node:18-alpine as frontend-build

WORKDIR /app/web

# Copy package files
COPY web/package.json web/package-lock.json* ./

# Install dependencies
RUN npm ci

# Copy source
COPY web/src ./src
COPY web/public ./public 2>/dev/null || true
COPY web/index.html web/tsconfig.json web/vite.config.ts ./

# Build
RUN npm run build

# Stage 3: Final production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from Stage 1
COPY --from=backend /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy application code
COPY src/ /app/src/
COPY requirements.txt .

# Copy built frontend from Stage 2
COPY --from=frontend-build /app/web/dist /app/public

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose ports
EXPOSE 8000 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run backend (frontend served by nginx in docker-compose)
CMD ["python", "-m", "uvicorn", "architect.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
