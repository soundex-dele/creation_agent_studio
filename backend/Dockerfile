FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements/production.txt
COPY . /app
RUN mkdir -p /var/log/agent_studio /app/media /app/staticfiles \
    && DJANGO_SETTINGS_MODULE=backend.settings.production \
       SECRET_KEY=build-only-secret-key-that-is-long-enough-and-never-used-at-runtime \
       python manage.py collectstatic --noinput
CMD ["daphne", "-b", "0.0.0.0", "-p", "8080", "backend.asgi:application"]
