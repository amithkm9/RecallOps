FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS dependencies
WORKDIR /build
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 \
    ENVIRONMENT=production FIXTURE_DIR=/app/data/fixtures FRONTEND_DIST=/app/frontend/dist
WORKDIR /app
COPY --from=dependencies /install /usr/local
COPY backend/ /app/backend/
COPY data/fixtures/ /app/data/fixtures/
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY scripts/start.sh /app/start.sh
RUN useradd --uid 10001 --create-home recallops && chmod +x /app/start.sh
USER recallops
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/api/health',timeout=4)"
CMD ["/app/start.sh"]
