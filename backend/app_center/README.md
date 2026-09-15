# Application Center packages

Each direct child directory is one trusted, bundled application. It must contain
an `application.yaml` manifest. Directory names use `snake_case`; the public
application ID in the manifest uses a lowercase slug.

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

The sync command is idempotent. Development deployments follow a changed
manifest revision; production deployments are never switched automatically.
Removing a package does not drop its tables or historical catalog records.
