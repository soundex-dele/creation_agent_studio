# 在线文档

Bundled application ID and renderer key: `documents`. Django label:
`online_documents` (a stable migration identifier).

The workspace supports Tiptap rich text, one-second debounced autosave,
optimistic version checks, private documents and per-member viewer/editor grants.
Only the owner manages grants or deletes documents. All access requires active
organization membership and permission to run this application.

The assistant reuses the configured `general` agent and durable Run workers.
Each document/user pair owns a separate private conversation. User messages carry
the saved document version and selected text/positions; the server supplies the
document context. Results never update documents automatically. The UI verifies
the version and selection before applying a result, then uses the regular save
endpoint. Missing agent deployment does not affect editing.

AI context is limited to 60,000 characters per request. Document JSON is limited
to 1 MB of UTF-8 JSON, depth 30, and 20,000 nodes. Only supported editor nodes and
HTTP(S)/mailto links are accepted. No images, attachments or HTML injection.

Deleting a document removes its grants and conversations. Durable Run audit data
is retained but document Run endpoints deny access once the document is gone.
There is no recycle bin or version-history UI in this release. Conflict recovery
supports downloading the local draft or copying it into a new private document.

From the repository root on Windows:

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py migrate online_documents --noinput
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package documents
```

Restart backend/execution workers after deployment so package discovery loads the
new Django application and URLs. The existing production frontend must be rebuilt.

Tests:

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest app_center/documents/backend/tests
cd ..\frontend
npm run test -- src/pages/Apps/__tests__/documents.test.ts
npm run build
```
