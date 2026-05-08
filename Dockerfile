FROM node:16-bullseye AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build -- --configuration production


FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY SoftwareEngineerTeam.py backend_api.py ./
COPY --from=frontend-build /app/frontend/dist/ai-swe-team-console ./frontend/dist/ai-swe-team-console

ENV PORT=10000
CMD ["sh", "-c", "python -m uvicorn backend_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
