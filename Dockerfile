FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN mkdir -p /app/data

# tzdata для правильной TZ внутри контейнера + базовые CA
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

# Создадим пользователя без root и каталоги под volume/логи/данные
RUN useradd -m -u 10001 appuser \
 && mkdir -p /app/src /app/logs /app/data \
 && chown -R appuser:appuser /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ./src /app/src
ENV PYTHONPATH=/app/src

USER appuser

CMD ["python", "-m", "app.main"]