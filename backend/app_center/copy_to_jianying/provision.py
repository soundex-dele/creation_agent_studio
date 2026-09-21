from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="copy-to-jianying",
        skill_description="将口播文案、旁白或文章制作成可编辑剪映草稿，包含分镜脚本、画面、配音、字幕与时间线。",
    )
