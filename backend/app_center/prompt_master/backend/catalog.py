SCENES = {
    "general": "通用", "writing": "写作", "coding": "编程", "learning": "学习",
    "office": "办公", "image": "绘图", "video": "视频",
}

TEMPLATES = [
    ("writing", "公众号文章", "写一篇面向新手的露营装备选购文章，帮助读者按预算做选择。"),
    ("writing", "产品文案", "为一款新产品撰写介绍文案，清楚表达它适合谁、解决什么问题。"),
    ("coding", "实现新功能", "为现有项目实现一个新功能，请先明确技术栈、输入输出和验收要求。"),
    ("coding", "排查代码问题", "分析一段出现错误的代码，定位原因，给出修复方案与验证方法。"),
    ("learning", "制定学习计划", "为我制定一个能够坚持执行的学习计划，包含练习与阶段检查。"),
    ("learning", "理解一个概念", "用适合初学者的例子解释一个复杂概念，并设计练习检验理解。"),
    ("office", "项目方案", "整理一份可执行的项目方案，明确目标、交付物、时间安排与风险。"),
    ("office", "工作汇报", "把我的工作记录整理成汇报，突出进展、问题和下一步行动。"),
    ("image", "产品展示图", "为一款产品设计展示图，明确主体、背景、构图、光线和视觉风格。"),
    ("image", "文章封面", "设计一张文章封面，画面要契合主题，预留清晰的标题区域。"),
    ("video", "产品短片", "设计一段产品展示视频，包含镜头运动、主体动作、节奏与声音建议。"),
    ("video", "氛围场景", "设计一段有故事氛围的视频，明确场景、人物动作、镜头衔接与时长。"),
]


def catalog():
    return {"scenes": [{"value": key, "label": label} for key, label in SCENES.items()],
            "templates": [{"id": f"{scene}-{i}", "scene": scene, "title": title, "topic": topic}
                          for i, (scene, title, topic) in enumerate(TEMPLATES)]}
