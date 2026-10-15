from django.db import migrations
from django.utils.dateparse import parse_datetime

TABLES = ("kitchen_assistant_record", "kitchen_assistant_operation")


def tenant_states(apps, schema_editor):
    State = apps.get_model("kitchen_assistant", "KitchenState")
    if schema_editor.connection.vendor != "postgresql":
        yield from State.objects.all().iterator()
        return
    Organization = apps.get_model("enterprise", "Organization")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.organization_id', true)")
        previous = cursor.fetchone()[0] or ""
        try:
            for organization_id in Organization.objects.values_list("id", flat=True).iterator():
                cursor.execute("SELECT set_config('app.organization_id', %s, true)", [str(organization_id)])
                yield from State.objects.filter(organization_id=organization_id).iterator()
        finally:
            cursor.execute("SELECT set_config('app.organization_id', %s, true)", [previous])


def move_history(apps, schema_editor):
    Record = apps.get_model("kitchen_assistant", "KitchenRecord")
    for state in tenant_states(apps, schema_editor):
        for record in state.data.get("records", []):
            Record.objects.get_or_create(state_id=state.pk, record_id=record["id"], defaults={
                "organization_id": state.organization_id, "data": record,
                "finished_at": parse_datetime(record["finishedAt"]),
            })
        state.data = {**state.data, "records": []}
        state.save(update_fields=["data"])


def restore_history(apps, schema_editor):
    Record = apps.get_model("kitchen_assistant", "KitchenRecord")
    for state in tenant_states(apps, schema_editor):
        records = Record.objects.filter(state_id=state.pk).order_by("-finished_at", "-id")
        state.data = {**state.data, "records": [row.data for row in records]}
        state.save(update_fields=["data"])


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(f'CREATE POLICY "tenant_isolation" ON "{table}" '
                           "USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
                           "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)")


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("kitchen_assistant", "0003_kitchenoperation_kitchenrecord")]
    operations = [migrations.RunPython(move_history, restore_history), migrations.RunPython(enable_rls, disable_rls)]
