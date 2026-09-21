from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="write-image-text-copy",
        skill_description="创作和优化图文作品的标题、封面、逐页文案与发布配文。",
    )
