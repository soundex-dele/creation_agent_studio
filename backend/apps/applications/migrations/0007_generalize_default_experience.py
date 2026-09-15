from django.db import migrations


GENERAL_SYSTEM_PROMPT = """你是一个通用 AI 助手，可以帮助用户分析问题、整理信息、制定计划并完成任务。

请先理解用户的目标、背景和约束；信息不足时提出必要问题，并用清晰、专业的方式给出可执行的结果。"""


def generalize_defaults(apps, schema_editor):
    Agent = apps.get_model("agents", "Agent")
    AgentDraft = apps.get_model("catalog", "AgentDraft")
    Application = apps.get_model("applications", "Application")
    ApplicationDraft = apps.get_model("catalog", "ApplicationDraft")

    agent = Agent.objects.filter(slug="general").first()
    if agent is not None:
        Agent.objects.filter(pk=agent.pk).update(
            name="通用助手",
            description="通用 AI 助手，适用于没有指定专用智能体的对话。",
        )
        draft = AgentDraft.objects.filter(agent_id=agent.pk).first()
        if draft is not None:
            content = dict(draft.content or {})
            content["system_prompt"] = GENERAL_SYSTEM_PROMPT
            AgentDraft.objects.filter(pk=draft.pk).update(content=content)

    application = Application.objects.filter(slug="creative-chat").first()
    if application is None:
        application = Application.objects.filter(slug="general-chat").first()
    if application is None:
        return

    Application.objects.filter(pk=application.pk).update(
        slug="general-chat",
        name="通用助手",
        description="使用智能体和引导问题处理日常任务",
        tags=["聊天", "智能体", "效率"],
        developer="Agent Studio",
    )
    draft = ApplicationDraft.objects.filter(application_id=application.pk).first()
    if draft is not None:
        content = dict(draft.content or {})
        profile = dict(content.get("chat_profile") or {})
        profile.update({
            "welcome_message": "告诉我你的目标，我会和你一起分析并完成任务。",
            "input_placeholder": "描述你的需求…",
            "empty_state_title": "今天想完成什么？",
        })
        content["chat_profile"] = profile
        content["guided_prompts"] = [
            {
                "id": "action-plan",
                "key": "action-plan",
                "title": "制定行动计划",
                "description": "",
                "icon": "🧭",
                "prompt_template": "请将下面的目标拆解为清晰、可执行的行动计划：\n{goal}\n约束条件：{constraints}",
                "action": "preview",
                "is_featured": True,
                "order": 0,
                "questions": [
                    {"id": "goal", "key": "goal", "label": "目标", "type": "text", "required": True, "order": 0, "options": []},
                    {"id": "constraints", "key": "constraints", "label": "约束条件", "type": "text", "required": False, "order": 1, "options": []},
                ],
            },
            {
                "id": "summarize",
                "key": "summarize",
                "title": "整理信息要点",
                "description": "",
                "icon": "📝",
                "prompt_template": "请整理下面的信息，提炼重点、结论和待办事项：\n{content}",
                "action": "preview",
                "is_featured": True,
                "order": 1,
                "questions": [
                    {"id": "content", "key": "content", "label": "待整理内容", "type": "text", "required": True, "order": 0, "options": []},
                ],
            },
            {
                "id": "analyze-options",
                "key": "analyze-options",
                "title": "分析解决方案",
                "description": "",
                "icon": "💡",
                "prompt_template": "请分析下面的问题，给出可行方案、主要取舍和建议：\n{problem}",
                "action": "preview",
                "is_featured": True,
                "order": 2,
                "questions": [
                    {"id": "problem", "key": "problem", "label": "需要解决的问题", "type": "text", "required": True, "order": 0, "options": []},
                ],
            },
        ]
        ApplicationDraft.objects.filter(pk=draft.pk).update(content=content)


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0006_move_agent_definition_to_catalog"),
        ("applications", "0006_chat_application_subtype"),
        ("catalog", "0001_initial"),
    ]

    operations = [migrations.RunPython(
        generalize_defaults, migrations.RunPython.noop
    )]
