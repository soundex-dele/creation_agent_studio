# Project agent instructions

- Do not use the Codex in-app browser for verification, visual QA, or local web testing in this repository unless the user explicitly requests it in a future message.
- Prefer automated tests, type checks, linting, production builds, and non-browser inspection for verification.
- Run all backend Python commands in the project virtual environment. On Windows, use `backend\venv\Scripts\python.exe` from the repository root or `.\venv\Scripts\python.exe` from `backend` for Django management commands, pytest, scripts, and package operations; do not use the system Python interpreter.
