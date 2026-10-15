"""Production formats shared by input validation, generation and exports."""

DEFAULT_FORMAT = "talking_head"
FORMAT_LABELS = {
    "talking_head": "真人口播",
    "screencast": "录屏演示",
    "animation": "动画演示",
    "live_action": "实景拍摄",
    "mixed": "混合形式",
}
FORMAT_DIRECTIONS = {
    "talking_head": "以真人面对镜头讲述为主。每个分镜写清景别、机位、人物动作与表情、口播节奏及必要的辅助字幕；准备清单包含收音、布光和提词。",
    "screencast": "以屏幕操作录制为主，不安排真人出镜。每个分镜写清展示的页面或界面区域、鼠标或键盘操作、操作顺序、屏幕变化、重点高亮和同步解说；准备清单包含演示环境、示例数据和录屏设置。资料未提供的界面名称与功能不得编造成事实，待确认内容须明确标注。",
    "animation": "以动画画面演示为主，不安排真人拍摄或真实录屏。每个分镜写清图形、文字或角色、构图、元素入场退场、运动过程、转场及同步旁白；准备清单包含字体、配色与图形素材。为了导入动画制作，最多30个分镜，总时长不超过120秒。",
    "live_action": "以真实场景中的拍摄为主。每个分镜写清地点、人物或物体、景别、机位与运镜、动作、环境声及解说；准备清单包含场地、道具、设备与拍摄顺序。用户未提供的经历或现场情况只能作为待拍摄建议。",
    "mixed": "结合用户制作条件合理组合真人口播、录屏、动画或实景，不要求每种都使用。每个分镜的画面描述开头标明该镜头的具体形式，并写清对应的执行步骤、形式间转场与声音衔接；准备清单按所用形式分类。",
}


def format_instruction(brief):
    selected = brief.get("production_format", DEFAULT_FORMAT)
    if selected not in FORMAT_LABELS:
        raise ValueError("不支持的视频形式。")
    return (
        f"\n用户选择的视频形式：{FORMAT_LABELS[selected]}。必须按此形式设计选题呈现方式和分镜，不照搬参考作品的制作形式。"
        + FORMAT_DIRECTIONS[selected]
        + "分镜时间用连续的起止秒数，画面描述须可执行，spoken 只填写该镜头实际朗读的文字；无口播的镜头填写空字符串，不把动作说明写入旁白。遵守用户的目标时长和制作条件。"
    )
