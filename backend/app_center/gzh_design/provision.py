from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="gzh-design",
        skill_description="将 Markdown、Word、PDF 或纯文本转换为可粘贴到公众号编辑器的合规 HTML。",
    )
