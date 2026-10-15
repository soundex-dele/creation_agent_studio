"""Topic planning and frozen evidence shared by generation and manual saves."""
from .content import text, strings


TOPIC_INSTRUCTION = '''直接根据源码快照策划恰好5个不同的内容选题，不需要先输出功能报告。
用户方向非空时，所有选题均围绕该方向；留空时推荐不同的切入角度。
每个选题都要有提供的证据片段支持，区分文档描述、代码实现和待核事项。
只看到文档、接口声明、测试或TODO不能声称功能已经实现；未运行代码，不得声称实测效果。
不要编造能力、操作步骤、效果数据或个人经历，也不要用相同标题换词凑数。
资料不足以支持5个不同选题或指定方向时，只返回 {"insufficient_reason":"具体说明缺少哪些资料或依据"}。
否则只返回 {"topics":[{"title":"标题","angle":"切入角度","audience":"适合人群",
"outline":["内容提纲"],"evidence_ids":["e1"],"notes":["待核实事项"]}]}。
每项outline包含1至5条，notes最多5条。标题不超过200字，angle/audience各不超过500字。
整份JSON控制在6000字符以内。不生成正文、功能报告或分镜；不能自行提供引用路径。'''


class InsufficientEvidence(ValueError):
    """A material gap cannot be repaired by inventing more topics."""


def validate_topics(value, evidence):
    if not isinstance(value, dict):
        raise ValueError('选题结果必须为对象。')
    if value.get('insufficient_reason'):
        reason = text(value['insufficient_reason'], '资料不足说明', 2000, False)
        raise InsufficientEvidence('源码资料不足：' + reason)
    rows = value.get('topics')
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError('需要5个有依据的不同选题；资料不足时请返回 insufficient_reason。')
    topics, titles = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('选题格式无效。')
        title = text(row.get('title'), '选题标题', 200, False).strip()
        if title in titles:
            raise ValueError('选题标题不能重复。')
        titles.add(title)
        ids = list(dict.fromkeys(strings(row.get('evidence_ids'), '选题证据', 30)))
        if not ids or any(identifier not in evidence for identifier in ids):
            raise ValueError('每个选题必须引用本次读取的源码证据。')
        outline = strings(row.get('outline'), '内容提纲', 5)
        if not outline or any(not item.strip() for item in outline):
            raise ValueError('选题需要非空内容提纲。')
        topics.append({'id': f't{index + 1}', 'title': title,
            'angle': text(row.get('angle'), '切入角度', 500, False),
            'audience': text(row.get('audience'), '适合人群', 500, False),
            'outline': outline, 'notes': strings(row.get('notes', []), '待核实事项', 5),
            'evidence_ids': ids})
    used = {identifier for topic in topics for identifier in topic['evidence_ids']}
    return {'topics': topics, 'evidence': {key: row for key, row in evidence.items() if key in used}}


def topic_material(task, topic_id):
    topic = next((row for row in task.output.get('topics', []) if row['id'] == topic_id), None)
    if topic is None:
        raise ValueError('所选选题不存在，请重新选择选题。')
    evidence = task.output.get('evidence', {})
    if not topic['evidence_ids'] or any(key not in evidence for key in topic['evidence_ids']):
        raise ValueError('所选选题的源码依据不可用，请重新生成选题。')
    return topic, {'features': [], 'evidence': {key: evidence[key] for key in topic['evidence_ids']}}


def validate_topic_document(document):
    if document.get('schema_version') != 2:
        raise ValueError('选题写作只接受新版文案格式。')
    for row in document['paragraphs']:
        if row['feature_ids'] or not row['evidence_ids']:
            raise ValueError('选题文案每段必须保留源码依据，功能编号应为空。')
    return document
