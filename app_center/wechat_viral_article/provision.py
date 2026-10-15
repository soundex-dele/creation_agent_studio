from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="wechat-viral-article",
        skill_description="撰写、改写和优化公众号文章，并完成标题、选题与合规检查。",
    )
