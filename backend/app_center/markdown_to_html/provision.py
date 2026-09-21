from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="baoyu-markdown-to-html",
        skill_description="将 Markdown 转为带主题和内联样式的 HTML，支持公众号排版和文末引用。",
    )
