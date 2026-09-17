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
`--package contacts` and `--organization <uuid>`.

The sync command is idempotent. When a package manifest sets `activate: true`,
its active deployment follows the latest changed manifest revision. Removing a
package does not drop its tables or historical catalog records.
