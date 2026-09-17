from django.db import migrations, models


def rename_creator_role(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(role="creator").update(role="member")


def restore_creator_role(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(role="member").update(role="creator")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("users", "0002_alter_user_api_key_userapikey")]

    operations = [
        migrations.RunPython(rename_creator_role, restore_creator_role),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "管理员"),
                    ("professional", "专业用户"),
                    ("member", "成员"),
                    ("viewer", "查看者"),
                ],
                default="member",
                max_length=20,
            ),
        ),
    ]
