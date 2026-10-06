from django.db import migrations


def rename_cowork(apps, schema_editor):
    Application = apps.get_model('applications', 'Application')
    Application.objects.using(schema_editor.connection.alias).filter(slug='cowork').update(
        name='对话',
        description='通过持续对话处理日常需求，围绕文件夹组织项目，与 AI 协作完成任务。',
    )


class Migration(migrations.Migration):
    dependencies = [('applications', '0012_personal_form_presets')]
    operations = [migrations.RunPython(rename_cowork, migrations.RunPython.noop)]
