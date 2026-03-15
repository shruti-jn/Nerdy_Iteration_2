# ── Stage 1: Build frontend ─────────────────────────────────────────────────
FROM node:18-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python backend + static frontend ──────────────────────────────
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies (cached layer)
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./

# Copy frontend build output into static/ for FastAPI to serve
COPY --from=frontend-build /app/frontend/dist ./static

# Create logs directory
RUN mkdir -p logs

EXPOSE 8000

# Production: no --reload, single worker (WebSocket sessions are stateful)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
