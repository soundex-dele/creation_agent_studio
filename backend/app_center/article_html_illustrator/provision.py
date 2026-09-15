from app_center.chat_skill_app import provision_chat_skill_definition


SYSTEM_PROMPT = """你是文章 HTML 配图助手。每次任务必须使用 baoyu-article-html-illustrator Skill。先分析文章结构与视觉机会，再生成 outline.md 和一组自包含、固定尺寸、文字清晰、可编辑的 HTML/CSS 配图。严格保持系列视觉一致，不按字面描绘比喻，不虚构文章没有的数据。应用提示词已完成设置确认时，不得再次询问。不要使用内置浏览器；除非用户明确提出，否则不导出 PNG。"""


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="baoyu-article-html-illustrator",
        skill_description="分析文章并生成整套可编辑、自包含的 HTML/CSS 配图。",
        agent_slug="article-html-illustrator-assistant",
        agent_name="文章 HTML 配图助手",
        agent_description="根据文章结构生成一致、可编辑的 HTML 配图。",
        agent_icon="🧩",
        system_prompt=SYSTEM_PROMPT,
    )
