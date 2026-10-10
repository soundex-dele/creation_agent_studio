import copy
import json
import math
import uuid


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


def narration(doc):
    return '\n'.join(s['narration'] for s in doc['scenes'])


def markdown(doc):
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
    if not doc['scenes']:
        raise ValueError('请先生成视频分镜。')
    return {'source': narration(doc), 'task': 'draft', 'aspect': doc['aspect'],
            'duration': '保留完整原稿；预计 ' + str(sum(s['seconds'] for s in doc['scenes'])) + ' 秒，以配音实测为准',
            'voice': 'auto', 'add_broll': 'disabled', 'assets': '', 'broll_directory': '',
            'requirements': '静态源码解读，不冒充实测。模拟界面标明示意。\n' + markdown(doc).split('## 素材准备')[0] +
                            '\n素材准备：\n' + '\n'.join(doc['checklist']), 'output_directory': '', 'drafts_root': ''}


def animation(doc):
    from app_center.animation_studio.backend.documents import empty_document, validate_document as validate_animation
    if not doc['scenes'] or len(doc['scenes']) > 30:
        raise ValueError('动画需要 1–30 个分镜，请另存调整后的文案。')
    if sum(s['seconds'] for s in doc['scenes']) > 120:
        raise ValueError('动画超过 120 秒，请另存精简稿后导入。')
    result = copy.deepcopy(empty_document())
    result.update(aspect=doc['aspect'], prompt='源码功能介绍；画面为示意，不冒充真实录屏。\n' + narration(doc))
    if len(result['prompt']) > 16000:
        raise ValueError('动画正文超过 16000 字符，请精简后导入。')
    result['scenes'] = [{'id': str(uuid.uuid4()), 'title': '', 'body': '', 'narration': s['narration'],
        'description': '示意动画：' + s['visual'], 'frames': max(1, round(s['seconds'] * 30)), 'assets': [],
        'locked': False, 'style': {}, 'source': ''} for s in doc['scenes']]
    total = sum(s['frames'] for s in result['scenes'])
    if total < 150:
        result['scenes'][-1]['frames'] += 150 - total
    return validate_animation(result)
