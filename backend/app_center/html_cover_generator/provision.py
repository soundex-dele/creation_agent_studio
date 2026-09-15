from app_center.chat_skill_app import provision_chat_skill_definition


SYSTEM_PROMPT = """你是 HTML 封面设计助手。每次任务必须使用 baoyu-html-cover Skill。根据用户确认的六维设置生成自包含、固定尺寸、可编辑的 HTML/CSS/SVG 封面，确保 40–60% 留白、单一视觉锚点、克制用色和清晰文字层级。标题必须逐字使用，不得改写。应用提示词已完成设置确认时，不得再次询问。不要使用内置浏览器；除非用户明确提出，否则不导出 PNG。"""


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="baoyu-html-cover",
        skill_description="用纯 HTML/CSS/SVG 生成像素级、可编辑的文章封面。",
        agent_slug="html-cover-designer-assistant",
        agent_name="HTML 封面设计助手",
        agent_description="根据结构化需求生成自包含 HTML 文章封面。",
        agent_icon="🖼️",
        system_prompt=SYSTEM_PROMPT,
    )
