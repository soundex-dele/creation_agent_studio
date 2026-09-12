# Enterprise deployment and operations

Creation Agent Studio now uses a control-plane/data-plane architecture:

- Django is the durable control plane for organizations, RBAC, agents, versions,
  deployments, policy, audit, quota, knowledge, evaluations and integrations.
- `run_job_worker` claims persistent application jobs from PostgreSQL. Job
  events, retries, heartbeat and reconnect state survive web-process restarts.
- GraphFlow provides the interactive runtime. Every tenant receives an isolated
  working directory and organization-specific model routing.
- Redis carries WebSocket events, cache and API throttling. PostgreSQL remains
  the source of truth. Uploaded assets use Django Storage so S3/OSS can be
  enabled without changing business APIs.

## Production start

1. Copy `backend/.env.example` to `backend/.env` and replace every secret.
2. Configure `GRAPHFLOW_*`, or create organization ProviderConfig and
   SecretReference records. SecretReference stores only an environment/Vault
   reference, never a provider secret.
3. Run `docker compose -f backend/docker-compose.yml up --build -d`.
4. Verify `GET /healthz/` and `GET /readyz/`.
5. Open `http://localhost:3000/enterprise` after signing in.

The stack starts frontend, ASGI web, PostgreSQL, Redis, a persistent job worker
and the automation scheduler. Apply retention periodically with:

```shell
python manage.py enforce_retention
```

## Tenant and identity

Every user receives a personal organization. Requests select a tenant using
`X-Organization-ID`. Membership roles are owner, admin, developer, operator,
auditor and viewer. Enterprise APIs include OIDC/SAML provider discovery and a
SCIM 2.0 Users surface at `/api/enterprise/scim/v2/Users`.

SSO metadata, client IDs and claim mappings are stored in IdentityProvider.
Client secrets are SecretReference values. OIDC uses Authorization Code + PKCE,
state validation, server-side token/userinfo exchange, verified email/domain
checks, durable external-identity binding and a one-time frontend exchange.
SAML metadata can be governed in the same control plane, but signed assertion
validation is intentionally not exposed until a production SAML adapter and
certificate trust policy are configured.

Private installations default to `SINGLE_TENANT_MODE=True`; multi-tenant
operators must explicitly set it to `False`. The first user provisions the configured enterprise
workspace and becomes its owner; later users join with
`SINGLE_TENANT_DEFAULT_ROLE`. The browser no longer selects or submits a tenant,
and organization-free `/api/runs` and `/api/applications/...` aliases are
enabled. The canonical Organization foreign keys and PostgreSQL RLS scope stay
in place for policy, audit and defense in depth.

## Agent release lifecycle

1. Create a draft containing prompt, model, tools, skills, knowledge,
   guardrails and a validated DAG workflow.
2. Submit it and have an organization administrator approve it.
3. Run an EvaluationSuite. Production deployment is blocked when a configured
   suite has no passing result for that version.
4. Deploy independently to development, staging or production. Rollback swaps
   the current and previous version atomically.

## Governance and observability

- GovernancePolicy controls retention, PII redaction, model/tool allowlists,
  blocked terms, network allowlists and export policy.
- API keys are hashed, scoped, expirable, auditable and revocable.
- RunTrace, TraceSpan, UsageRecord and AuditLog expose lifecycle, latency,
  tokens, cost, actor, request ID and resource context.
- QuotaPolicy enforces token, cost and concurrent-run budgets.
- OrganizationRateThrottle applies the organization-specific per-minute limit.
- Knowledge APIs ingest, chunk and return ranked results with citations.
- Automation supports API dispatch and five-field cron scheduling.

Enterprise endpoints under `/api/enterprise/` include `organizations`,
`providers`, `secrets`, `identity-providers`, `governance`, `quota`, `usage`,
`traces`, `audit-logs`, `knowledge-bases`, `evaluations`, `connectors` and
`automations`.

The `/enterprise` console exposes organization membership/RBAC, quotas,
governance, model and secret references, knowledge documents, evaluation cases,
connector invocation, automation dispatch, identity providers, traces, audit,
and the agent draft/review/deploy/rollback lifecycle.

## Verification

```shell
cd backend
python manage.py makemigrations --check --dry-run
python manage.py check --deploy --settings=backend.settings.production
python -m pytest -q

cd ../frontend
npm ci
npm test -- --run
npm run build
npm audit
```
