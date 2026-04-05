FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/opencrab_root

COPY . /app/opencrab_root

RUN pip install --upgrade pip \
    && pip install -e /app/opencrab_root \
    && pip install -r /app/opencrab_root/apps/api/requirements.txt

EXPOSE 8001

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
