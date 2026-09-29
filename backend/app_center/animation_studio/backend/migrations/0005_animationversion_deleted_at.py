from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animation_studio", "0004_history_and_rls")]

    operations = [
        migrations.AddField(
            model_name="animationversion",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
