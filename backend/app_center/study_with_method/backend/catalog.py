"""Stable, low-input catalog for the learning companion UI."""

from .models import GradeStage, Subject


SUBJECT_CATALOG = {
    Subject.CHINESE: {
        "label": "语文", "icon": "BookOpen", "color": "#9B5D55",
        "chapters": ["现代文阅读", "文言文与古诗词", "语言文字运用", "写作"],
    },
    Subject.MATH: {
        "label": "数学", "icon": "Sigma", "color": "#326B5B",
        "chapters": ["函数", "三角函数", "数列", "立体几何", "解析几何", "概率统计", "导数"],
    },
    Subject.ENGLISH: {
        "label": "英语", "icon": "Languages", "color": "#4D6FA8",
        "chapters": ["词汇与语法", "阅读理解", "完形与七选五", "应用文写作", "读后续写"],
    },
    Subject.PHYSICS: {
        "label": "物理", "icon": "Atom", "color": "#5965A5",
        "chapters": ["运动与力", "能量与动量", "电场与电路", "磁场与电磁感应", "实验探究"],
    },
    Subject.CHEMISTRY: {
        "label": "化学", "icon": "FlaskConical", "color": "#95577E",
        "chapters": ["无机物与反应", "化学反应原理", "物质结构", "有机化学", "化学实验"],
    },
    Subject.BIOLOGY: {
        "label": "生物", "icon": "Dna", "color": "#4C8057",
        "chapters": ["分子与细胞", "遗传与进化", "稳态与调节", "生物与环境", "实验探究"],
    },
    Subject.POLITICS: {
        "label": "思想政治", "icon": "Landmark", "color": "#A56A3F",
        "chapters": ["中国特色社会主义", "经济与社会", "政治与法治", "哲学与文化", "选修模块"],
    },
    Subject.HISTORY: {
        "label": "历史", "icon": "ScrollText", "color": "#846744",
        "chapters": ["中国古代史", "中国近现代史", "世界史", "选择性必修", "史料与论述"],
    },
    Subject.GEOGRAPHY: {
        "label": "地理", "icon": "Globe2", "color": "#3D7B7C",
        "chapters": ["自然地理", "人文地理", "区域发展", "资源环境与国家安全", "地图与综合题"],
    },
}

GRADE_CATALOG = [
    {"value": GradeStage.HIGH_1, "label": "高一"},
    {"value": GradeStage.HIGH_2, "label": "高二"},
    {"value": GradeStage.HIGH_3, "label": "高三"},
]

CURRICULUM_VERSIONS = ["通用高中课程", "人教版", "北师大版", "苏教版"]
SUBJECT_CURRICULUM_VERSIONS = {
    Subject.MATH: [{"id": "xj-math-current", "label": "湘教版（现行）"}],
    Subject.HISTORY: [{"id": "pep-history-current", "label": "统编人教版（现行）"}],
}


def catalog_payload():
    return {
        "grades": GRADE_CATALOG,
        "subjects": [
            {
                "value": value,
                **config,
                "curriculum_versions": [
                    item["id"] for item in SUBJECT_CURRICULUM_VERSIONS.get(
                        value, [{"id": version, "label": version} for version in CURRICULUM_VERSIONS]
                    )
                ],
                "curriculum_version_options": SUBJECT_CURRICULUM_VERSIONS.get(
                    value, [{"id": version, "label": version} for version in CURRICULUM_VERSIONS]
                ),
            }
            for value, config in SUBJECT_CATALOG.items()
        ],
    }
