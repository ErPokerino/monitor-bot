FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------

FROM python:3.12-slim AS backend

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

COPY src/ src/
COPY config.toml ./
COPY templates/ templates/

COPY --from=frontend /build/dist /app/static

ENV PORT=8080
EXPOSE 8080

CMD ["uv", "run", "uvicorn", "monitor_bot.app:app", "--host", "0.0.0.0", "--port", "8080"]
