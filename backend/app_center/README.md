# Application Center packages

Each direct child directory is one trusted, bundled application. It must contain
an `application.yaml` manifest. Directory names use `snake_case`; the public
application ID in the manifest uses a lowercase slug.

A child may be a complete Git submodule. `creation_master` demonstrates a
package with isolated Qt and React variants: frontend metadata is declared in
the manifest, while each variant keeps its own runtime and dependencies.

Applications that own relational tables declare a Django `AppConfig` and keep
their migrations below their package. App labels and migration names are stable
database identifiers and must never be renamed after release.

Deployment order:

1. `python manage.py validate_app_center`
2. `python manage.py migrate --noinput`
3. `python manage.py sync_app_center`
4. start web and execution workers

Run the complete sequence with:

```console
python scripts/sync_app_center.py
```

Use `--validate-only` for a read-only validation, or limit synchronization with
`--package creation-toolbox` and `--organization <uuid>`.

The sync command is idempotent. When a package manifest sets `activate: true`,
its active deployment follows the latest changed manifest revision. Removing a
package does not drop its tables or historical catalog records.

## Guided content applications

These packages use the shared chat renderer and content creation agent. Users
fill in a form, review the generated prompt, and continue editing in chat.

| Package | Application | Required Skill |
| --- | --- | --- |
| `write-image-text-copy` | 图文文案 | `write-image-text-copy` |
| `write-short-video-copy` | 短视频文案 | `write-short-video-copy` |
| `markdown-to-html` | Markdown 转 HTML | `baoyu-markdown-to-html` |
| `html-to-paged-cards` | HTML 分页图文 | `html-to-paged-cards` |

Install the complete Skill directories (including references and scripts) under
`CODEX_SKILLS_DIRECTORY` on the execution host. The manifests bind these existing
Skills; they do not copy them into this repository. Markdown conversion requires
Bun or npx and the Skill's JavaScript dependencies. Mermaid PNG rendering also
requires Chrome, Chromium, or Edge; the form can select source-code output instead.

HTML pagination requires Node.js, Playwright, and Chromium (or an installed
Chrome/Edge fallback). It consumes existing static HTML, preserves the original
file, and produces paginated HTML, an index, and a validation report. PNG export
is opt-in. Oversized blocks use extended pages by default; strict sizing reports
an error instead of clipping content. Keep the original image and style resources
available because output pages still reference them.

From the repository root on Windows, validate and synchronize with the project
virtual environment (repeat synchronization for each desired package):

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package write-image-text-copy
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package write-short-video-copy
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package markdown-to-html
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package html-to-paged-cards
```
