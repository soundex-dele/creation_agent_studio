import uuid

import app_center.creation_toolbox.backend.models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


TENANT_TABLES = (
    "creation_toolbox_topics",
    "creation_toolbox_stage_events",
    "creation_toolbox_deliverables",
    "creation_toolbox_publications",
    "creation_toolbox_metric_snapshots",
)


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            cursor.execute(
                f'CREATE POLICY "tenant_isolation" ON "{table}" '
                "USING (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting("
                "'app.organization_id', true), '')::uuid)"
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS "tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("creation_toolbox", "0001_initial_compacted"),
        ("enterprise", "0007_compacted_0007_0008"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="creationproject", name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="creationproject", name="owner",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="owned_creation_projects", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="creationproject", name="planned_publish_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="creationproject", name="reviewer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_creation_projects", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="creationproject", name="stage",
            field=models.CharField(choices=[("planning", "策划"), ("scripting", "脚本"), ("materials", "素材"), ("producing", "制作中"), ("review", "待审核"), ("published", "已发布"), ("retrospective", "复盘完成")], db_index=True, default="planning", max_length=24),
        ),
        migrations.AddField(
            model_name="creationproject", name="stage_changed_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="creationproject", name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="creationproject", name="target_platforms",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name="ProjectStageEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("from_stage", models.CharField(choices=[("planning", "策划"), ("scripting", "脚本"), ("materials", "素材"), ("producing", "制作中"), ("review", "待审核"), ("published", "已发布"), ("retrospective", "复盘完成")], max_length=24)),
                ("to_stage", models.CharField(choices=[("planning", "策划"), ("scripting", "脚本"), ("materials", "素材"), ("producing", "制作中"), ("review", "待审核"), ("published", "已发布"), ("retrospective", "复盘完成")], max_length=24)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="creation_stage_events", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stage_events", to="creation_toolbox.creationproject")),
            ],
            options={"db_table": "creation_toolbox_stage_events", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="TopicIdea",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("normalized_title", models.CharField(db_index=True, max_length=200)),
                ("notes", models.TextField(blank=True)),
                ("source_name", models.CharField(blank=True, max_length=200)),
                ("source_url", models.URLField(blank=True, max_length=1000)),
                ("target_platforms", models.JSONField(blank=True, default=list)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("status", models.CharField(choices=[("pending", "待评估"), ("ready", "待创作"), ("adopted", "已采用"), ("postponed", "暂缓"), ("archived", "已归档")], db_index=True, default="pending", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="creation_topics", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_creation_topics", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="topics", to="creation_toolbox.creationworkspace")),
            ],
            options={"db_table": "creation_toolbox_topics", "ordering": ["-updated_at", "title"]},
        ),
        migrations.AddField(
            model_name="creationproject", name="topic",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="projects", to="creation_toolbox.topicidea"),
        ),
        migrations.CreateModel(
            name="VideoDeliverable",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("version_label", models.CharField(default="v1", max_length=80)),
                ("platform", models.CharField(blank=True, choices=[("douyin", "抖音"), ("kuaishou", "快手"), ("wechat_channels", "视频号"), ("xiaohongshu", "小红书"), ("bilibili", "B站"), ("other", "其他")], max_length=24)),
                ("file", models.FileField(blank=True, max_length=500, null=True, upload_to=app_center.creation_toolbox.backend.models.deliverable_upload_path)),
                ("external_url", models.URLField(blank=True, max_length=1000)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("review_status", models.CharField(choices=[("draft", "草稿"), ("pending", "待审核"), ("approved", "已通过"), ("changes_requested", "需修改")], db_index=True, default="draft", max_length=24)),
                ("review_note", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="creation_deliverables", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deliverables", to="creation_toolbox.creationproject")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_creation_deliverables", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "creation_toolbox_deliverables", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Publication",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("platform", models.CharField(choices=[("douyin", "抖音"), ("kuaishou", "快手"), ("wechat_channels", "视频号"), ("xiaohongshu", "小红书"), ("bilibili", "B站"), ("other", "其他")], db_index=True, max_length=24)),
                ("platform_name", models.CharField(blank=True, max_length=80)),
                ("account_name", models.CharField(max_length=160)),
                ("title", models.CharField(blank=True, max_length=300)),
                ("external_post_id", models.CharField(blank=True, max_length=200)),
                ("post_url", models.URLField(blank=True, max_length=1000)),
                ("published_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="creation_publications", to=settings.AUTH_USER_MODEL)),
                ("deliverable", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="publications", to="creation_toolbox.videodeliverable")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publications", to="creation_toolbox.creationproject")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publications", to="creation_toolbox.creationworkspace")),
            ],
            options={"db_table": "creation_toolbox_publications", "ordering": ["-published_at"]},
        ),
        migrations.CreateModel(
            name="MetricSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("observed_on", models.DateField(db_index=True)),
                ("impressions", models.PositiveBigIntegerField(default=0)),
                ("views", models.PositiveBigIntegerField(default=0)),
                ("completions", models.PositiveBigIntegerField(default=0)),
                ("likes", models.PositiveBigIntegerField(default=0)),
                ("comments", models.PositiveBigIntegerField(default=0)),
                ("shares", models.PositiveBigIntegerField(default=0)),
                ("saves", models.PositiveBigIntegerField(default=0)),
                ("followers_gained", models.PositiveBigIntegerField(default=0)),
                ("conversions", models.PositiveBigIntegerField(default=0)),
                ("average_watch_seconds", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("extra_metrics", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="creation_metric_snapshots", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="enterprise.organization")),
                ("publication", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metric_snapshots", to="creation_toolbox.publication")),
            ],
            options={"db_table": "creation_toolbox_metric_snapshots", "ordering": ["-observed_on", "-created_at"], "constraints": [models.UniqueConstraint(fields=("publication", "observed_on"), name="unique_creation_metric_snapshot_day")]},
        ),
        migrations.AddIndex(model_name="topicidea", index=models.Index(fields=["workspace", "status"], name="ct_topic_workspace_status")),
        migrations.AddConstraint(model_name="videodeliverable", constraint=models.CheckConstraint(condition=models.Q(("file__isnull", False), models.Q(("external_url", ""), _negated=True), _connector="OR"), name="creation_deliverable_has_source")),
        migrations.AddIndex(model_name="publication", index=models.Index(fields=["workspace", "platform"], name="ct_pub_workspace_platform")),
        migrations.AddConstraint(model_name="publication", constraint=models.UniqueConstraint(condition=models.Q(("external_post_id", ""), _negated=True), fields=("workspace", "platform", "account_name", "external_post_id"), name="unique_creation_publication_external_id")),
        migrations.AddConstraint(model_name="publication", constraint=models.UniqueConstraint(condition=models.Q(("post_url", ""), _negated=True), fields=("workspace", "platform", "account_name", "post_url"), name="unique_creation_publication_url")),
        migrations.RunPython(enable_rls, disable_rls),
    ]
