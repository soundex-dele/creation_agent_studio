from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="wechat-viral-article",
        skill_description="公众号爆款选题、标题方向与内容策划。",
    )
