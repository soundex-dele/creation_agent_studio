#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8080}"

SERVICE_NAMES=()
SERVICE_PIDS=()
SHUTTING_DOWN=0

usage() {
  cat <<'EOF'
Usage: ./deploy.sh

Bootstrap and start the local Agent Studio stack:
  1. Apply Django migrations
  2. Create a superuser when one does not exist
  3. Synchronize every App Center package
  4. Start the frontend, backend, and all execution worker pools

Optional environment variables:
  DJANGO_SUPERUSER_USERNAME  Create this superuser non-interactively
  DJANGO_SUPERUSER_PASSWORD  Password for non-interactive creation
  DJANGO_SUPERUSER_EMAIL     Email for non-interactive creation
  BACKEND_HOST               Backend listen address (default: 0.0.0.0)
  BACKEND_PORT               Backend listen port (default: 8080)

If no superuser exists and the credential variables are not set, the script
runs Django's interactive createsuperuser command when attached to a terminal.
Press Ctrl-C to stop all three services.
EOF
}

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  printf '\nError: %s\n' "$*" >&2
  exit 1
}

find_python() {
  local candidate

  for candidate in \
    "${BACKEND_DIR}/.venv/bin/python" \
    "${BACKEND_DIR}/venv/bin/python"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

superuser_exists() {
  local query

  if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
    query="username=os.environ['DJANGO_SUPERUSER_USERNAME'], is_superuser=True"
  else
    query="is_superuser=True"
  fi

  "${PYTHON_BIN}" "${BACKEND_DIR}/manage.py" shell -c \
    "import os, sys; from django.contrib.auth import get_user_model; sys.exit(0 if get_user_model().objects.filter(${query}).exists() else 1)"
}

create_superuser() {
  if superuser_exists; then
    if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
      log "Superuser '${DJANGO_SUPERUSER_USERNAME}' already exists; skipping creation."
    else
      log "A superuser already exists; skipping creation."
    fi
    return
  fi

  if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
    [[ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]] || fail \
      "DJANGO_SUPERUSER_PASSWORD is required for non-interactive superuser creation."
    [[ -n "${DJANGO_SUPERUSER_EMAIL:-}" ]] || fail \
      "DJANGO_SUPERUSER_EMAIL is required for non-interactive superuser creation."

    log "Creating superuser '${DJANGO_SUPERUSER_USERNAME}'."
    "${PYTHON_BIN}" "${BACKEND_DIR}/manage.py" createsuperuser --noinput
    return
  fi

  if [[ -t 0 && -t 1 ]]; then
    log "No superuser exists. Starting interactive superuser creation."
    "${PYTHON_BIN}" "${BACKEND_DIR}/manage.py" createsuperuser
    return
  fi

  fail "No superuser exists. Set DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD, and DJANGO_SUPERUSER_EMAIL."
}

start_service() {
  local name="$1"
  shift

  log "Starting ${name}."
  "$@" &
  SERVICE_NAMES+=("${name}")
  SERVICE_PIDS+=("$!")
}

stop_services() {
  local pid

  if (( SHUTTING_DOWN )); then
    return
  fi
  SHUTTING_DOWN=1

  if (( ${#SERVICE_PIDS[@]} == 0 )); then
    return
  fi

  log "Stopping services."
  for pid in "${SERVICE_PIDS[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait "${SERVICE_PIDS[@]}" 2>/dev/null || true
}

wait_for_services() {
  local index pid status

  while true; do
    for index in "${!SERVICE_PIDS[@]}"; do
      pid="${SERVICE_PIDS[${index}]}"
      if ! kill -0 "${pid}" 2>/dev/null; then
        set +e
        wait "${pid}"
        status=$?
        set -e
        printf '\n%s exited with status %s.\n' \
          "${SERVICE_NAMES[${index}]}" "${status}" >&2
        return "${status}"
      fi
    done
    sleep 1
  done
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
[[ $# -eq 0 ]] || fail "Unknown argument: $1 (use --help for usage)."

PYTHON_BIN="$(find_python)" || fail \
  "Backend virtual environment not found. Create backend/.venv and install the requirements first."
NPM_BIN="$(command -v npm)" || fail "npm is not installed or is not available on PATH."
[[ -d "${FRONTEND_DIR}/node_modules" ]] || fail \
  "Frontend dependencies are missing. Run 'cd frontend && npm ci' first."

trap stop_services EXIT INT TERM

log "Applying database migrations."
"${PYTHON_BIN}" "${BACKEND_DIR}/manage.py" migrate --noinput

# User records depend on the migrated schema, so this must follow migrations on
# a clean installation even though it is part of the initial bootstrap.
create_superuser

log "Synchronizing all App Center packages."
"${PYTHON_BIN}" "${BACKEND_DIR}/manage.py" sync_app_center

start_service "frontend" \
  bash -c 'cd "$1" && exec "$2" run dev -- --host 0.0.0.0' \
  _ "${FRONTEND_DIR}" "${NPM_BIN}"

start_service "backend" \
  bash -c 'cd "$1" && exec "$2" manage.py runserver "$3:$4"' \
  _ "${BACKEND_DIR}" "${PYTHON_BIN}" "${BACKEND_HOST}" "${BACKEND_PORT}"

start_service "worker" \
  bash -c 'cd "$1" && exec "$2" manage.py run_execution_coordinator --worker-pool all' \
  _ "${BACKEND_DIR}" "${PYTHON_BIN}"

log "Agent Studio is running. Frontend: http://localhost:3030"
wait_for_services
