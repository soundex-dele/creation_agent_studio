FROM node:24-bookworm-slim AS codex-cli

ARG CODEX_CLI_VERSION=0.155.0
RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}" \
    && npm cache clean --force

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 agentstudio \
    && useradd --uid 10001 --gid agentstudio --create-home --shell /usr/sbin/nologin agentstudio
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/bin/codex /usr/local/bin/codex
COPY --from=codex-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY backend/requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements/production.txt
COPY --chown=agentstudio:agentstudio backend/ /app
COPY --chown=agentstudio:agentstudio teaching_data/ /teaching_data
RUN mkdir -p /data/artifacts /data/agent-workspaces /data/media \
        /home/agentstudio/.codex /app/staticfiles \
    && chown -R agentstudio:agentstudio /data /home/agentstudio /app/staticfiles
USER agentstudio:agentstudio
RUN DJANGO_SETTINGS_MODULE=backend.settings.production \
       SECRET_KEY=build-only-secret-key-that-is-long-enough-and-never-used-at-runtime \
       python manage.py collectstatic --noinput
CMD ["daphne", "-b", "0.0.0.0", "-p", "8080", "backend.asgi:application"]
