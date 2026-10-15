from modules.platform_api.chat_skills import provision_chat_skill_definition


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="write-short-video-copy",
        skill_description="创作和优化短视频口播、旁白、字幕、分镜与发布文案。",
    )
