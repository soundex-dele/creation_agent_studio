import uuid

import django.db.models.deletion
from django.db import migrations, models

import apps.conversations.models


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0011_backfill_supervisor_agent_conversations'),
        ('enterprise', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='MessageAttachment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('file', models.FileField(max_length=500, upload_to=apps.conversations.models.message_attachment_upload_to)),
                ('original_name', models.CharField(max_length=255)),
                ('content_type', models.CharField(max_length=100)),
                ('byte_size', models.PositiveBigIntegerField()),
                ('width', models.PositiveIntegerField(blank=True, null=True)),
                ('height', models.PositiveIntegerField(blank=True, null=True)),
                ('checksum_sha256', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='conversations.conversation')),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='conversations.message')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='message_attachments', to='enterprise.organization')),
            ],
            options={
                'db_table': 'message_attachments',
                'ordering': ['created_at', 'id'],
                'indexes': [models.Index(fields=['conversation', 'message'], name='message_att_convers_c98bce_idx')],
            },
        ),
    ]
