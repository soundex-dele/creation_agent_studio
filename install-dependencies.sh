#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Match deploy.sh's interpreter selection; never install into host Python.
if [[ -x "${PROJECT_ROOT}/backend/.venv/bin/python" ]]; then
  VENV_PYTHON="${PROJECT_ROOT}/backend/.venv/bin/python"
elif [[ -x "${PROJECT_ROOT}/backend/venv/bin/python" ]]; then
  VENV_PYTHON="${PROJECT_ROOT}/backend/venv/bin/python"
else
  # Listing/help use only the standard library and do not create an environment.
  for argument in "$@"; do
    if [[ "$argument" == "--list-apps" || "$argument" == "--help" || "$argument" == "-h" ]]; then
      exec "${PYTHON_BOOTSTRAP:-python3}" "${PROJECT_ROOT}/deploy/install_dependencies.py" "$@"
    fi
  done
  for argument in "$@"; do
    if [[ "$argument" == "--dry-run" ]]; then
      printf 'Would create backend/.venv using %s. Run without --dry-run to bootstrap it.\n' "${PYTHON_BOOTSTRAP:-python3}"
      exit 0
    fi
  done
  "${PYTHON_BOOTSTRAP:-python3}" -m venv "${PROJECT_ROOT}/backend/.venv"
  VENV_PYTHON="${PROJECT_ROOT}/backend/.venv/bin/python"
fi
exec "${VENV_PYTHON}" "${PROJECT_ROOT}/deploy/install_dependencies.py" "$@"
