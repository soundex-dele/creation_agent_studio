from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workflows', '0004_workflow_dag'),
    ]

    operations = [
        migrations.AddField(
            model_name='workflow',
            name='execution_mode',
            field=models.CharField(
                choices=[('manual', '手动执行'), ('automatic', '自动执行')],
                default='automatic',
                max_length=20,
            ),
        ),
    ]
