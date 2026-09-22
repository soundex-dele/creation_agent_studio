# Server deployment runbook

For a host installation without containers, run `bash install-dependencies.sh
--system-deps --with-codex` from the repository root before the migration/startup
steps. On Windows use `powershell -ExecutionPolicy Bypass -File
.\install-dependencies.ps1 -SystemDeps -WithCodex`. See the root README for
prerequisites, optional desktop/mobile packages, and dry-run flags. These scripts
install into the backend virtual environment and npm package directories; they
do not install services or change `.env`. The Compose flow below installs its
dependencies inside the images instead.

## 1. Prepare the host

- Use a supported Linux host with Docker Engine and Docker Compose v2.
- Clone with `--recurse-submodules`. Every enabled App Center submodule must be
  pinned to the commit recorded by this repository.
- The `teaching_data` submodule is required by the Study With Method package.
  Before deployment, run `backend/.venv/bin/python backend/manage.py
  validate_teaching_data`; a missing or invalid dataset intentionally blocks
  application synchronization.
- Copy `backend/.env.example` to a secret-managed path outside the repository
  when possible. Pass it with `BACKEND_ENV_FILE`.
- Generate independent random values for `SECRET_KEY`, `DB_ADMIN_PASSWORD`,
  `DB_PASSWORD`, and `REDIS_PASSWORD`. Never reuse provider API keys.

Production registration is disabled by default. Keep it disabled for private
installations and provision accounts through the Django administrator or SSO.
There is no built-in administrator password: Django stores only password hashes.

## 2. Configure DNS and TLS

Compose publishes the frontend only on `127.0.0.1:3000`; PostgreSQL, Redis,
and Django are not published on the host. Install a host reverse proxy and
forward the public HTTPS origin to that address. `deploy/Caddyfile.example`
is a minimal Caddy configuration.

Set these values to the final HTTPS origin:

```dotenv
ALLOWED_HOSTS=studio.example.com
CORS_ALLOWED_ORIGINS=https://studio.example.com
REST_FRAMEWORK_NUM_PROXIES=2
JWT_REFRESH_COOKIE_SECURE=True
```

Use `REST_FRAMEWORK_NUM_PROXIES=1` when the bundled Nginx is the only proxy.
Do not publish ports 8080, 5432, or 6379.

## 3. Start and bootstrap

```bash
cd backend
BACKEND_ENV_FILE=/etc/agent-studio/backend.env docker compose up --build -d
BACKEND_ENV_FILE=/etc/agent-studio/backend.env docker compose exec web \
  python manage.py createsuperuser
```

`createsuperuser` asks for the initial administrator username and password; the
password entered there is the login password. To manage accounts in the web UI,
set `DJANGO_ADMIN_ENABLED=True`, restart the `web` service, and open `/admin/`.
Keep `REGISTRATION_ENABLED=False`; users created in Django Admin can still log
in normally. If the administrator password is lost, set a new one rather than
trying to retrieve the old hash:

```bash
BACKEND_ENV_FILE=/etc/agent-studio/backend.env docker compose exec web \
  python manage.py changepassword ADMIN_USERNAME
```

Sign in once with the bootstrap administrator so the single-tenant workspace
is claimed by the intended owner. Verify both endpoints through HTTPS:

```bash
curl --fail https://studio.example.com/healthz/
curl --fail https://studio.example.com/readyz/
```

## 4. Backup and recovery

Back up all of the following as one recovery set:

- PostgreSQL with `pg_dump --format=custom`;
- the `runtime_data` volume, unless both media and artifacts have been moved to
  versioned object storage;
- the deployment environment/secret references in a secret manager;
- the exact image digests and Git revision used for the release.

Run backups from a scheduler outside this Compose project and encrypt them
before copying off-host. A backup is not accepted until a restore into a clean
staging environment has passed login, media download, knowledge search, and a
sample Agent run. Record the tested RPO and RTO.

## 5. Release gate

Every release must pass the repository CI, build both images from a clean
checkout, run migrations against a restored production snapshot, and verify
`/readyz/`. Do not use `docker compose up --build` as an unreviewed production
upgrade mechanism; build immutable images in CI and deploy their digests.

Provider keys previously committed to Git must be revoked at the provider.
Deleting the string from the current checkout does not invalidate it or remove
it from history.

## Remote access / 我的电脑

Apply migrations, rebuild the frontend, and synchronize the `my-computer` package
alongside the existing packages. The normal Compose bootstrap already runs
migrations and `sync_app_center` for all packages. The bundled Nginx forwards
`/ws/remote/connector/` upgrades and disables HTTP/SSE proxy buffering.

Server settings:

```dotenv
REMOTE_RELAY_ENABLED=True
REMOTE_ACCESS_HOST_ENABLED=False
# Uses the normal Redis configuration unless explicitly overridden:
# REMOTE_RELAY_REDIS_URL=redis://:password@redis:6379/0
```

Use the ASGI entrypoint `backend.asgi:application` (Daphne, as in the existing
container). WSGI cannot serve connector WebSockets. Multiple ASGI processes must
share the same database and Redis. Single-process installations may explicitly
enable memory relay as described below. Redis relay uses Pub/Sub only, so normal Redis
persistence does not retain forwarded bodies. Keep infrastructure logs/APM from
capturing bodies or authorization headers on remote routes. No end-to-end
encryption is added: HTTP pairs with WS, HTTPS with WSS.

For a source checkout on the controlled computer, `./deploy.sh` now manages
`run_remote_connector` together with the backend and execution workers. It sets
`REMOTE_CONNECTOR_LOCAL_URL` to the configured backend port and syncs
`my-computer`. The connector stays idle until enabled in Settings. To start it
separately, use the project virtual environment:

```bash
cd backend
REMOTE_ACCESS_HOST_ENABLED=True .venv/bin/python manage.py migrate
REMOTE_ACCESS_HOST_ENABLED=True .venv/bin/python manage.py run_remote_connector
```

The separately started Django API must also have `REMOTE_ACCESS_HOST_ENABLED=True`.
`REMOTE_CONNECTOR_LOCAL_URL` must be a loopback HTTP origin. Windows uses
`backend\venv\Scripts\python.exe backend\manage.py run_remote_connector` from the
repository root, with the same environment settings. The packaged desktop
launcher enables host capability and manages the connector process automatically;
its API origin is `http://127.0.0.1:8765`. PyInstaller includes the connector and
WebSocket dependency. Install updated requirements before building a package.

1. On the computer, open **设置 → 远程访问**, enter the server root URL and computer
   name, explicitly select a local user and organization, save, and enable.
2. Generate a pairing code. On the phone, log in to the server, open **我的电脑**,
   and enter the code within 10 minutes.
3. Confirm the displayed server account on the computer. Choose the online
   computer on the phone to start or resume a conversation.
4. Disable access to disconnect while retaining the binding; unbind to revoke
   credentials. If the server is unreachable during unbind, access is disabled
   locally and revocation must be retried when connectivity returns.

Closing the browser does not stop the connector. Stopping the local backend,
connector or desktop application makes the computer offline. No operating system
service, login startup task, wake-on-LAN or offline instruction queue is installed.
The first release does not transfer attachments or provide a remote desktop.

Protocol and endpoint details: [REMOTE_ACCESS_API.md](REMOTE_ACCESS_API.md).
Run remote access tests with the backend virtual environment. Set
`REMOTE_TEST_REDIS_BINARY=/path/to/redis-server` to include the real Redis
cross-process test; it creates an isolated, temporary local Redis instance and
verifies that no data keys are written.

## Development: start both frontends and backends

Use two terminals at the repository root. These commands work on one computer,
or on two computers with a checkout and installed dependencies on each. Both use
HTTP and no Redis. The script initializes the database, prompts for an initial
administrator when needed, and synchronizes the My Computer application.

Terminal 1 — relay server, frontend **3031**, backend **8081**:

```bash
DJANGO_SETTINGS_MODULE=backend.settings.development \
DATABASE_ENGINE=sqlite REDIS_ENABLED=False REMOTE_RELAY_REDIS_URL= \
JWT_REFRESH_COOKIE_SECURE=False JWT_REFRESH_COOKIE_NAME=agent_studio_relay_refresh \
SQLITE_PATH="$PWD/backend/dev-relay.sqlite3" \
REMOTE_RELAY_ENABLED=True REMOTE_RELAY_ALLOW_MEMORY=True \
REMOTE_ACCESS_HOST_ENABLED=False EXECUTION_WORKERS_ENABLED=False \
BACKEND_PORT=8081 FRONTEND_PORT=3031 \
bash ./deploy.sh
```

This creates a separate relay database and runs only its frontend and backend.
The distinct refresh-cookie name prevents logins on different localhost ports
from overwriting the controlled computer's refresh cookie.

Terminal 2 — controlled computer, frontend **3030**, backend **8080**:

```bash
DJANGO_SETTINGS_MODULE=backend.settings.development \
DATABASE_ENGINE=sqlite REDIS_ENABLED=False REMOTE_RELAY_REDIS_URL= \
JWT_REFRESH_COOKIE_SECURE=False \
SQLITE_PATH="$PWD/backend/dev-computer.sqlite3" \
REMOTE_ACCESS_HOST_ENABLED=True REMOTE_RELAY_ENABLED=False \
EXECUTION_WORKERS_ENABLED=True BACKEND_PORT=8080 FRONTEND_PORT=3030 \
bash ./deploy.sh
```

This creates a separate computer-side development database and also starts the
execution worker and remote connector. To use existing local data instead,
replace `SQLITE_PATH` with the absolute path to that database. The relay and
controlled computer must never share a database. Absolute paths keep management
commands and the running backend on the same database regardless of working directory.

Open `http://localhost:3030` on the controlled computer and configure
**设置 → 远程访问**. On one machine, the server URL is
`http://127.0.0.1:3031`; on two machines, use `http://SERVER_IP:3031`.
Open that server URL in the other browser/phone, log in, and claim the code in
**我的电脑**, then confirm the account on the computer. The two installations
have their own accounts. The server must stay at one ASGI serving process.

`deploy.sh` passes its backend origin to Vite using `VITE_PROXY_TARGET`, and
`FRONTEND_PORT` controls the frontend listener. A port conflict fails instead of
silently selecting another frontend port. If starting Vite separately, run
`VITE_PROXY_TARGET=http://127.0.0.1:8081 npm --prefix frontend run dev -- --host 0.0.0.0 --port 3031 --strictPort`
for the server frontend. On both sides, Ctrl+C in the script terminal stops that
side's managed processes. Existing processes occupying these ports must be
stopped first, or choose a different pair of ports.

## Standalone HTTP relay without Redis

This deployment uses one production Daphne process with in-memory forwarding,
and Caddy to serve the frontend and proxy HTTP/SSE/WebSocket on port 3000.
`DEBUG` remains off. The existing Compose stack includes Redis and is not used
for this setup. HTTP uses `ws://` for the connector; traffic is unencrypted.

The backend also needs production dependencies (including Sentry's SDK, which
the production settings import even when reporting is disabled):

```bash
backend/.venv/bin/python -m pip install -r backend/requirements/production.txt
```

For a new source installation, install the project dependencies and Caddy, then
copy `backend/.env.remote-http.example` to `backend/.env`. For an existing
installation, merge the following settings into its `.env`, preserving its
database and persistent `SECRET_KEY`:

```dotenv
REDIS_ENABLED=False
REMOTE_RELAY_ENABLED=True
REMOTE_RELAY_REDIS_URL=
REMOTE_RELAY_ALLOW_MEMORY=True
REMOTE_ACCESS_HOST_ENABLED=False
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
JWT_REFRESH_COOKIE_SECURE=False
ALLOWED_HOSTS=YOUR_SERVER_IP,localhost,127.0.0.1
REST_FRAMEWORK_NUM_PROXIES=1
```

Replace `YOUR_SERVER_IP` with the actual IP or hostname, without scheme or port.
The new-install template uses SQLite; an existing PostgreSQL installation can
keep its database settings. A new installation needs a secret of at least 50
characters; generate one with the project virtual environment, save it in
`.env`, and retain it across restarts:

```bash
backend/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Initialize from the repository root (macOS/Linux):

```bash
cd backend
export DJANGO_SETTINGS_MODULE=backend.settings.production
.venv/bin/python manage.py migrate
.venv/bin/python manage.py sync_app_center
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

Create the administrator only on first installation. Start the backend from
`backend/`, with the production settings environment variable still set:

```bash
.venv/bin/python -m daphne -b 127.0.0.1 -p 8080 backend.asgi:application
```

In another terminal, build the frontend and start Caddy from the repository root:

```bash
npm --prefix frontend run build
APP_FRONTEND_ROOT="$PWD/frontend/dist" caddy run --config deploy/Caddyfile.http.example --adapter caddyfile
```

Open `http://YOUR_SERVER_IP:3000` to log in. Caddy serves the frontend and forwards
API, admin, static, health and WebSocket routes to Daphne. The example disables
proxy response buffering so SSE remains streaming. Use a process manager such
as systemd to keep these two processes running after the shell exits.

Run **exactly one** Daphne process/replica for this server; HTTP requests and
connector WebSockets must reach that same process. In-memory state and rate
limits are not shared across processes. For multiple workers or replicas,
configure shared Redis instead. A nonempty `REMOTE_RELAY_REDIS_URL` always selects
Redis; there is no automatic fallback on a Redis outage.

On the controlled computer, use `bash ./deploy.sh` as usual, with
`REMOTE_ACCESS_HOST_ENABLED=True`, `REMOTE_RELAY_ENABLED=False`, and local database
settings. Set `REDIS_ENABLED=False` there too if it has no Redis. In
**设置 → 远程访问**, enter `http://YOUR_SERVER_IP:3000`, select the local identity,
generate a code, claim it from the server's **我的电脑** page, and confirm the
account on the computer. The local launcher manages the connector and execution
workers; this relay-only server does not need to run either.

Verify production HTTP without Redis using isolated local databases:

```bash
backend/.venv/bin/python backend/scripts/test_remote_local.py --production-server
```
