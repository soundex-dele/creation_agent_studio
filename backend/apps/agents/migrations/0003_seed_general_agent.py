"""Seed the fallback agent used by conversations without an explicit agent."""
from django.db import migrations


GENERAL_SYSTEM_PROMPT = """你是一个通用 AI 助手，可以帮助用户分析问题、整理信息、制定计划并完成任务。

请先理解用户的目标、背景和约束；信息不足时提出必要问题，并用清晰、专业的方式给出可执行的结果。"""


def seed_general_agent(apps, schema_editor):
    User = apps.get_model('users', 'User')
    AgentCategory = apps.get_model('agents', 'AgentCategory')
    Agent = apps.get_model('agents', 'Agent')
    owner = User.objects.filter(is_superuser=True).first()
    if owner is None:
        owner, _ = User.objects.get_or_create(username='system')
    category, _ = AgentCategory.objects.get_or_create(
        slug='general', defaults={'name': '通用', 'order': 0})
    Agent.objects.get_or_create(
        slug='general',
        defaults={
            'name': '通用助手',
            'description': '通用 AI 助手，适用于没有指定专用智能体的对话。',
            'system_prompt': GENERAL_SYSTEM_PROMPT,
            'category': category,
            'created_by': owner,
            'is_public': True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [('agents', '0002_initial')]
    operations = [migrations.RunPython(
        seed_general_agent, migrations.RunPython.noop)]
