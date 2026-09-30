FROM python:3.13-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

COPY backend/requirements.lock ./requirements.lock
RUN pip install --require-hashes -r requirements.lock

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY tianyuan_quant_v10_2_multi_agent_files /app/tianyuan_quant_v10_2_multi_agent_files

RUN mkdir -p /app/storage /app/backend/app/storage /app/backend/app/storage/runs

EXPOSE 8000
CMD ["python", "-m", "app.main"]
