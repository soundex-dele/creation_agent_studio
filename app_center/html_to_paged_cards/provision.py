from app_center.chat_skill_app import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="html-to-paged-cards",
        skill_description="将已有文章 HTML 按实际排版高度拆成完整的多页图文，生成分页 HTML、预览索引与校验报告。",
    )
