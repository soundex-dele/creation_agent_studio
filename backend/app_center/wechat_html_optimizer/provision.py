from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="optimize-wechat-html",
        skill_description="优化已有 HTML 的移动端排版与微信公众号编辑器兼容性。",
    )
