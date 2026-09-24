# 想法&待办

Personal ideas, tasks and memos, installed per organization. The application catalog is
organization-visible; records are always scoped to organization, application,
and authenticated owner, including for organization administrators.

The React page lives in `frontend/src/pages/Apps/IdeasTodosPage.tsx` and uses the
platform application shell and API client. It does not require an execution worker.

## API

Under `/api/v1/organizations/{organization_id}/applications/{application_id}/ideas-todos`:

- `GET/POST /ideas`, `GET/PATCH/DELETE /ideas/{uuid}`
- `GET/POST /todos`, `GET/PATCH/DELETE /todos/{uuid}`
- `GET/POST /memos`, `GET/PATCH/DELETE /memos/{uuid}`

Single-tenant deployments also expose the existing organization-free aliases.
List responses use `{count, next, previous, results}`, with 20 rows per page.
All lists accept `page` and `search` (title and body/description).

Ideas contain `title`, `body`, `tags`, and `is_pinned`; `tag` filters by tag keyword.
They are ordered by pinned status, then most recently updated.

Memos contain `title`, `body`, and `is_pinned`, independently of ideas and todos.
They are ordered by pinned status, then most recently updated and ID. The memo
tab supports creating, editing, searching, pinning and deleting private records.
Apply the migrations below when upgrading to version 1.1.0.

Todos contain `title`, `description`, `priority` (1 low, 2 medium, 3 high),
`due_date` (nullable YYYY-MM-DD), `is_completed`, and read-only `completed_at`.
List filters: `status=pending|all|completed|today|overdue` (default pending),
`priority`, and `today=YYYY-MM-DD`. Today/overdue filters require the client's
local calendar date and exclude completed tasks. Dates have no time component;
there are no scheduled reminders. Results put incomplete tasks first, then
earliest due date (null last), highest priority, newest creation, and ID.

Titles are required and limited to 200 characters. Body/description is limited
to 20,000 characters. Ideas allow up to 20 distinct tags, 40 characters each.
Owner, organization, application and timestamps are assigned by the server.
PATCH completion records the transition time; repeating the same state preserves
it and restoring an incomplete task clears it. Deletes are permanent.

## Installation and checks (Windows, repository root)

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate ideas_todos --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package ideas-todos
```

Restart an already-running backend after installing a new Django application.
New migrations create only this application's tables and PostgreSQL tenant RLS.
No existing user data is migrated or seeded.

From `backend`, run `venv\Scripts\python.exe -m pytest app_center/ideas_todos/backend/tests`.
From `frontend`, run `npx vitest run src/pages/Apps/__tests__/ideasTodos.test.ts src/lib/__tests__/applicationCatalog.test.ts`
and `npm run build`. Verification uses automated tests; no browser is required.
