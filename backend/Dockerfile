# Build from the REPO ROOT:  docker build -f backend/Dockerfile -t smart-traffic .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/cameras.json .
COPY frontend-static ./frontend-static
ENV STATIC_DIR=/app/frontend-static

EXPOSE 8000
# $PORT is injected by Render/Railway/Heroku-style hosts
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
