"""Seed the default chat application against mutable Agent/Application models."""
from django.db import migrations


def seed_default_chat(apps, schema_editor):
    Application = apps.get_model('applications', 'Application')
    ApplicationCategory = apps.get_model('applications', 'ApplicationCategory')
    ApplicationAgentBinding = apps.get_model(
        'applications', 'ApplicationAgentBinding')
    ChatApplicationProfile = apps.get_model(
        'applications', 'ChatApplicationProfile')
    GuidedPrompt = apps.get_model('applications', 'GuidedPrompt')
    GuidedQuestion = apps.get_model('applications', 'GuidedQuestion')
    GuidedOption = apps.get_model('applications', 'GuidedOption')
    Agent = apps.get_model('agents', 'Agent')

    general = Agent.objects.filter(slug='general').first()
    if general is None:
        return
    category, _ = ApplicationCategory.objects.get_or_create(
        slug='chat', defaults={
            'name': '聊天应用',
            'description': '由智能体和 Skill 驱动的聊天应用',
            'icon': 'chat',
            'order': 0,
        })
    application, _ = Application.objects.get_or_create(
        slug='general-chat',
        defaults={
            'category': category,
            'name': '通用助手',
            'description': '使用智能体和引导问题处理日常任务',
            'icon': '✨',
            'color': '#6d5dfc',
            'tags': ['聊天', '智能体', '效率'],
            'developer': 'Agent Studio',
            'is_public': True,
            'created_by_id': general.created_by_id,
            'organization_id': general.organization_id,
            'kind': 'chat',
            'renderer_key': 'chat',
        },
    )
    ChatApplicationProfile.objects.get_or_create(
        application=application,
        defaults={
            'welcome_message': '告诉我你的目标，我会和你一起分析并完成任务。',
            'input_placeholder': '描述你的需求…',
            'empty_state_title': '今天想完成什么？',
            'allow_agent_selection': False,
            'allow_skill_selection': True,
        })
    ApplicationAgentBinding.objects.get_or_create(
        application=application, agent=general,
        defaults={'label': general.name, 'is_default': True, 'order': 0})
    prompts = [
        ('action-plan', '制定行动计划', '🧭',
         '请将下面的目标拆解为清晰、可执行的行动计划：\n{goal}\n约束条件：{constraints}', [
             ('goal', '目标', 'text', True, []),
             ('constraints', '约束条件', 'text', False, []),
         ]),
        ('summarize', '整理信息要点', '📝',
         '请整理下面的信息，提炼重点、结论和待办事项：\n{content}', [
             ('content', '待整理内容', 'text', True, []),
         ]),
        ('analyze-options', '分析解决方案', '💡',
         '请分析下面的问题，给出可行方案、主要取舍和建议：\n{problem}', [
             ('problem', '需要解决的问题', 'text', True, []),
         ]),
    ]
    for order, (key, title, icon, template, questions) in enumerate(prompts):
        prompt, _ = GuidedPrompt.objects.get_or_create(
            application=application, key=key,
            defaults={
                'title': title,
                'icon': icon,
                'prompt_template': template,
                'action': 'preview',
                'is_featured': True,
                'order': order,
            })
        for question_order, (question_key, label, question_type, required,
                             options) in enumerate(questions):
            question, _ = GuidedQuestion.objects.get_or_create(
                guided_prompt=prompt, key=question_key,
                defaults={
                    'label': label,
                    'type': question_type,
                    'required': required,
                    'order': question_order,
                })
            for option_order, (value, option_label) in enumerate(options):
                GuidedOption.objects.get_or_create(
                    question=question, value=value,
                    defaults={'label': option_label, 'order': option_order})


class Migration(migrations.Migration):
    dependencies = [
        ('applications', '0001_initial'),
        ('agents', '0003_seed_general_agent'),
    ]
    operations = [migrations.RunPython(
        seed_default_chat, migrations.RunPython.noop)]
