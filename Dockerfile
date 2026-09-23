FROM node:24-slim AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY frontend ./frontend
COPY index.html tsconfig.json vite.config.ts ./
RUN npm run build

FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY backend ./backend
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
COPY --from=frontend /app/dist ./dist
RUN useradd --create-home app && mkdir -p /app/data && chown app:app /app/data
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
