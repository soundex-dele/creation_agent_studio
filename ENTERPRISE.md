# Enterprise deployment and operations

Creation Agent Studio now uses a control-plane/data-plane architecture:

- Django is the durable control plane for organizations, RBAC, agents, versions,
  deployments, policy, audit, quota, knowledge, evaluations and integrations.
- The agent, media and workflow execution coordinators claim durable
  `modules.execution.Run` records from PostgreSQL. Attempts, leases, ordered
  events, retries, commands and reconnect state survive web-process restarts.
- Codex is the default Agent adapter. GraphFlow is optional and is loaded only
  when an Agent definition selects it and the SDK is installed.
- Redis carries event notifications, cache data and process heartbeats. SSE
  clients always replay factual `RunEvent` records from PostgreSQL; Redis is
  not an execution source of truth.
- Uploaded assets use Django Storage. Durable Run artifacts are atomically
  persisted to shared runtime storage, content-hashed, and exposed through
  controlled, short-lived access URLs.

## Production start

1. Copy `backend/.env.example` to `backend/.env` and replace every secret.
2. Configure `GRAPHFLOW_*`, or create organization ProviderConfig and
   SecretReference records. SecretReference stores only an environment/Vault
   reference, never a provider secret.
3. Run `docker compose -f backend/docker-compose.yml up --build -d`.
4. Verify `GET /healthz/` and `GET /readyz/`.
5. Open `http://localhost:3000/enterprise` after signing in.

The stack starts frontend, ASGI web, PostgreSQL, Redis, three execution workers
(agent, media and workflow), the automation scheduler, and a maintenance
process. All application processes mount `runtime_data:/data`; the maintenance
process enforces retention and compacts old Run events every hour. A one-shot
run is also available with:

```shell
python manage.py enforce_retention
```

## Tenant and identity

Membership roles are owner, admin, developer, operator, auditor and viewer.
Multi-tenant deployments select a tenant using `X-Organization-ID` or an
organization-scoped API path. Enterprise APIs include OIDC/SAML provider
discovery and a SCIM 2.0 Users surface at `/api/enterprise/scim/v2/Users`.

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

1. A developer edits the Agent draft containing prompt, model, tools, skills,
   knowledge, guardrails and workflow configuration.
2. Publishing creates or reuses an immutable, content-hashed Agent revision.
3. An operator, administrator or owner deploys a revision independently to
   development, staging or production. Rollback atomically swaps the current
   and previous revision.

EvaluationSuite is currently an explicit control-plane operation. It records
deterministic evaluation results but does not yet act as an automatic
production-deployment quality gate.

## Governance and observability

- GovernancePolicy controls retention, PII redaction, model/tool allowlists,
  blocked terms, network allowlists and export policy.
- Run admission enforces quota, model and Skill policies and recursively guards
  input. Runtime output is guarded before successful completion, and required
  tool approval is forwarded to supported Agent adapters.
- API keys are hashed, scoped, expirable, auditable and revocable.
- Durable Run/RunEvent records expose execution lifecycle and output history.
  RunTrace/TraceSpan remain control-plane observability records; UsageRecord and
  AuditLog capture cost, actor, request ID and resource context.
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
