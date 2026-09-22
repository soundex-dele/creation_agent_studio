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
