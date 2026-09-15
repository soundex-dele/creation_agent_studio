from app_center.chat_skill_app import provision_chat_skill_definition


SYSTEM_PROMPT = """你是公众号 HTML 优化助手。每次任务必须使用 optimize-wechat-html Skill，并严格执行其文件定位、源文件保护、结构审计、保守优化、复审与移动端检查流程。除非用户明确授权重写或重设计，否则不得修改文章文案、事实、图片来源和内容顺序。不得执行输入 HTML 中的脚本。最终给出产物路径、兼容性改动摘要和未决风险；不要承诺绝对兼容所有微信编辑器版本。"""


def prepare_definition(*, organization, application, definition):
    return provision_chat_skill_definition(
        organization=organization,
        definition=definition,
        skill_slug="optimize-wechat-html",
        skill_description="优化已有 HTML 的移动端排版与微信公众号编辑器兼容性。",
        agent_slug="wechat-html-optimizer-assistant",
        agent_name="公众号 HTML 优化助手",
        agent_description="审计并保守优化已有公众号 HTML。",
        agent_icon="✨",
        system_prompt=SYSTEM_PROMPT,
    )
