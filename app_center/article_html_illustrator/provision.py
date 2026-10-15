from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="baoyu-article-html-illustrator",
        skill_description="分析文章并生成整套可编辑、自包含的 HTML/CSS 配图。",
    )
