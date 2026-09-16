from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="baoyu-html-cover",
        skill_description="用纯 HTML/CSS/SVG 生成像素级、可编辑的文章封面。",
    )
