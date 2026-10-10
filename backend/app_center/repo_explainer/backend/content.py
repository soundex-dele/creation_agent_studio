import json
import math


def text(value, label, maximum=12000, blank=True):
    if not isinstance(value, str) or len(value) > maximum or (not blank and not value.strip()):
        raise ValueError(f'{label}必须是有效文本，最长 {maximum} 字符。')
    return value


def strings(value, label, maximum=100):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f'{label}格式无效。')
    return [text(v, label, 4000) for v in value]


def refs(row, features, evidence):
    feature_ids = strings(row.get('feature_ids', []), '功能引用')
    evidence_ids = strings(row.get('evidence_ids', []), '证据引用')
    if any(i not in features for i in feature_ids) or any(i not in evidence for i in evidence_ids):
        raise ValueError('文案引用了不存在的功能或证据。')
    return {'feature_ids': feature_ids, 'evidence_ids': evidence_ids, 'needs_review': True}


def validate_document(value, report):
    if not isinstance(value, dict) or len(json.dumps(value)) > 200000:
        raise ValueError('内容文档格式或长度无效。')
    features = {f['id'] for f in report['features']}
    evidence = report['evidence']
    if value.get('schema_version') == 2:
        return validate_copy(value, features, evidence)
    result = {'title': text(value.get('title'), '标题', 200, False),
              'cover': text(value.get('cover', ''), '封面', 200),
              'aspect': value.get('aspect', '16:9'), 'checklist': strings(value.get('checklist', []), '素材清单')}
    if result['aspect'] not in {'16:9', '9:16', '1:1'}:
        raise ValueError('画幅无效。')
    scenes = value.get('scenes', [])
    if not isinstance(scenes, list) or len(scenes) > 100:
        raise ValueError('分镜最多 100 个。')
    result['scenes'] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError('分镜格式无效。')
        seconds = scene.get('seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 600:
            raise ValueError('分镜时长必须为 0–600 秒之间的有限数值。')
        result['scenes'].append({**refs(scene, features, evidence), 'seconds': seconds,
            'narration': text(scene.get('narration', ''), '旁白'), 'visual': text(scene.get('visual', ''), '画面建议')})
    article = value.get('article', {})
    if not isinstance(article, dict):
        raise ValueError('图文格式无效。')
    sections = article.get('sections', [])
    if not isinstance(sections, list) or len(sections) > 100:
        raise ValueError('图文章节最多 100 个。')
    result['article'] = {'title': text(article.get('title', ''), '图文标题', 200),
                         'intro': text(article.get('intro', ''), '引言'), 'sections': []}
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError('图文章节格式无效。')
        result['article']['sections'].append({**refs(section, features, evidence),
            'heading': text(section.get('heading', ''), '章节标题', 200),
            'body': text(section.get('body', ''), '正文'), 'image': text(section.get('image', ''), '配图建议')})
    if not result['scenes'] and not sections:
        raise ValueError('至少需要视频分镜或图文正文。')
    result['needs_review'] = True
    return result


def validate_copy(value, features, evidence):
    if value.get('kind') not in {'video', 'image_text'}:
        raise ValueError('请选择视频文案或图文文案。')
    if any(key in value for key in ('scenes', 'article', 'images')):
        raise ValueError('只接受文案，不接受分镜或图文成品。')
    paragraphs = value.get('paragraphs')
    if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 100:
        raise ValueError('请提供 1–100 段正文。')
    result = {'schema_version': 2, 'kind': value['kind'],
        'title': text(value.get('title'), '标题', 200, False), 'cover': text(value.get('cover', ''), '封面', 200),
        'alternatives': strings(value.get('alternatives', []), '备选标题', 5),
        'publish_copy': text(value.get('publish_copy', ''), '发布配文'),
        'notes': strings(value.get('notes', []), '待核事项'), 'needs_review': True,
        'aspect': value.get('aspect', '16:9'), 'duration': value.get('duration', 60), 'paragraphs': []}
    if result['aspect'] not in {'16:9', '9:16', '1:1'}:
        raise ValueError('画幅无效。')
    if type(result['duration']) not in (int, float) or not math.isfinite(result['duration']) or not 5 <= result['duration'] <= 600:
        raise ValueError('预计时长须为 5–600 秒。')
    for row in paragraphs:
        if not isinstance(row, dict):
            raise ValueError('文案段落格式无效。')
        result['paragraphs'].append({**refs(row, features, evidence),
            'heading': text(row.get('heading', ''), '段落标题', 200), 'text': text(row.get('text'), '正文')})
    if not any(p['text'].strip() for p in result['paragraphs']):
        raise ValueError('请至少保留一段正文。')
    return result


def narration(doc):
    if doc.get('schema_version') == 2:
        return '\n\n'.join(p['text'] for p in doc['paragraphs']) if doc['kind'] == 'video' else ''
    return '\n'.join(s['narration'] for s in doc['scenes'])


def markdown(doc):
    if doc.get('schema_version') == 2:
        rows = [f"# {doc['title']}", f"封面：{doc['cover']}", '## 视频文案' if doc['kind'] == 'video' else '## 图文文案']
        for row in doc['paragraphs']:
            rows += ([f"### {row['heading']}"] if row['heading'] else []) + [row['text'],
                f"待核对；功能：{', '.join(row['feature_ids'])}；证据：{', '.join(row['evidence_ids'])}"]
        rows += ['## 发布配文', doc['publish_copy'], '## 备选标题', '\n'.join(doc['alternatives']), '## 待核事项', '\n'.join(doc['notes'])]
        if doc['kind'] == 'video': rows += [f"预计时长：{doc['duration']} 秒，以实际试读为准"]
        if doc.get('skill'): rows += [f"写作技能：{doc['skill']['slug']}（SHA-256：{doc['skill']['sha256']}）"]
        return '\n\n'.join(rows)
    article = doc['article']
    rows = [f"# {doc['title']}", f"封面：{doc['cover']}", '## 口播', narration(doc), '## 分镜']
    for i, s in enumerate(doc['scenes'], 1):
        rows += [f"### {i} · 预计 {s['seconds']} 秒", s['narration'], f"画面：{s['visual']}",
                 f"待核对；功能：{', '.join(s['feature_ids'])}；证据：{', '.join(s['evidence_ids'])}"]
    rows += ['## 素材准备', '\n'.join('- ' + t for t in doc['checklist']), f"# {article['title']}", article['intro']]
    for s in article['sections']:
        rows += [f"## {s['heading']}", s['body'], f"配图：{s['image']}",
                 f"待核对；证据：{', '.join(s['evidence_ids'])}"]
    return '\n\n'.join(rows)


def jianying(doc):
    source, duration = video_copy(doc)
    return {'source': source, 'task': 'draft', 'aspect': doc['aspect'],
            'duration': '保留完整原稿；预计 ' + str(duration) + ' 秒，以配音实测为准',
            'voice': 'auto', 'add_broll': 'disabled', 'assets': '', 'broll_directory': '',
            'requirements': '请根据完整口播文案设计分镜并制作剪映草稿。静态源码解读，不冒充实测，模拟界面标明示意。\n'
                + f"标题：{doc['title']}\n封面：{doc['cover']}", 'output_directory': '', 'drafts_root': ''}


def video_copy(doc):
    source = narration(doc)
    if not source.strip():
        raise ValueError('只有视频文案可以进入制作；图文文案仅编辑和导出。')
    duration = doc['duration'] if doc.get('schema_version') == 2 else sum(s['seconds'] for s in doc['scenes'])
    return source, duration


def animation(doc):
    from app_center.animation_studio.backend.documents import empty_document, validate_document as validate_animation
    source, duration = video_copy(doc)
    if duration > 120:
        raise ValueError('动画超过 120 秒，请另存精简稿后导入。')
    result = empty_document()
    result.update(aspect=doc['aspect'], prompt=f"请依据以下完整视频文案生成分镜，保留事实和限定；预计 {duration} 秒。画面为示意，不冒充真实录屏。\n标题：{doc['title']}\n口播文案：\n{source}")
    if len(result['prompt']) > 16000:
        raise ValueError('动画正文超过 16000 字符，请精简后导入。')
    return validate_animation(result)
