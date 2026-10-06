from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('conversations', '0002_conversation_scope')]
    operations = [migrations.AddField(
        model_name='conversation', name='messages_cleared_at',
        field=models.DateTimeField(null=True, blank=True),
    )]
