FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY tianyuan_quant_v10_2_multi_agent_files /app/tianyuan_quant_v10_2_multi_agent_files

RUN mkdir -p /app/storage /app/backend/app/storage /app/backend/app/storage/runs

EXPOSE 8000
CMD ["python", "-m", "app.main"]
