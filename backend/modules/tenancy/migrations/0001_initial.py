# Generated for the destructive V2 schema baseline.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("settings", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="v2_owned_organizations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "v2_organizations", "ordering": ("name", "id")},
        ),
        migrations.CreateModel(
            name="Membership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("owner", "Owner"), ("admin", "Administrator"), ("developer", "Developer"), ("operator", "Operator"), ("auditor", "Auditor"), ("viewer", "Viewer")], max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="v2_tenancy.organization")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="v2_organization_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "v2_organization_memberships",
                "constraints": [models.UniqueConstraint(fields=("organization", "user"), name="v2_unique_organization_membership")],
            },
        ),
    ]
