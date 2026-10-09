"""Execution handlers. All writes are guarded by the active execution lease."""
from django.utils import timezone
from . import models as m, analysis
from .collector_config import LocalDTKClient
from .provider import normalize_work, CollectionError
from .research import record_observation, task_scope, valid_date
import json


def model_evidence(value):
    """Keep signed media URLs out of model inputs and bound large research batches."""
    if isinstance(value, dict):
        return {k: model_evidence(v) for k, v in value.items() if k not in {'video_url', 'cover', 'media_urls', '_media_urls', 'media_key', 'key'}}
    if isinstance(value, list):
        return [model_evidence(v) for v in value]
    return value


def radar_evidence(rows):
    result = [{k: row[k] for k in ['id', 'account_id', 'title', 'description', 'basis', 'transcript', 'likes', 'comments', 'collects', 'published_at'] if k in row} for row in rows]
    limit = 2000
    while len(json.dumps(result, ensure_ascii=False)) > 150000 and limit >= 50:
        for row in result:
            for key in ['title', 'description', 'transcript']:
                if isinstance(row.get(key), str):
                    row[key] = row[key][:limit]
        limit //= 2
    return result


def validate_topics_report(value, allowed):
    topics = value.get('topics')
    if not isinstance(topics, list) or not 1 <= len(topics) <= 20:
        raise ValueError('主题报告必须包含1–20个主题。')
    for topic in topics:
        if not isinstance(topic, dict) or any(not isinstance(topic.get(k), str) or not topic[k].strip() or len(topic[k]) > 3000 for k in ['title', 'angle']):
            raise ValueError('主题标题或角度无效。')
        refs = topic.get('refs')
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in allowed for ref in refs):
            raise ValueError('主题引用不存在。')
    return {'topics': [{k: t[k] for k in ['title', 'angle', 'refs']} for t in topics]}


def validate_variants(value):
    output = {}
    for key in ['hooks', 'titles', 'covers']:
        rows = value.get(key)
        if not isinstance(rows, list) or len(rows) != 3:
            raise ValueError('每组必须恰好包含3个候选表达。')
        limit = 3000 if key == 'hooks' else 300
        if any(not isinstance(r, dict) or not isinstance(r.get('text'), str) or not r['text'].strip() or len(r['text']) > limit or not isinstance(r.get('angle'), str) or len(r['angle']) > 1000 for r in rows):
            raise ValueError('候选表达格式无效。')
        output[key] = [{'text': r['text'], 'angle': r['angle']} for r in rows]
    return output


def structured(task, prompt, data, config, validator, sink):
    for attempt in range(2):
        value = analysis.call_model(task, prompt, data, config, cancelled=lambda: sink.cancelled)
        try:
            return validator(value)
        except ValueError:
            if attempt:
                raise
            prompt += '\n上次结构或引用校验未通过，请严格遵循结构与引用范围。'


def refresh_work(task, work, client, payload, sink):
    from ..runtime import current
    data = normalize_work(client.detail(work.platform_id))
    if data['platform_id'] != work.platform_id:
        raise CollectionError('invalid')
    with current(payload, sink) as active:
        work.metadata = {k: v for k, v in data.items() if k != '_media_urls'}
        work.media_urls = data.pop('_media_urls', [])
        work.save(update_fields=['metadata', 'media_urls', 'updated_at'])
        point, created = record_observation(active, work, data, timezone.now())
        if created:
            from .subscriptions import growth_notice
            growth_notice(active, work, point)


def collect_comments(task, payload, sink, save, check):
    from ..runtime import current
    work = m.Work.objects.select_related('account').get(pk=task.input['work_ids'][0])
    client = LocalDTKClient(account=work.account, check=check)
    with current(payload, sink) as active:
        batch, _ = m.CommentBatch.objects.get_or_create(task=active, defaults={'work': work})
    parents, complete, warning = [], False, ''

    def persist(rows):
        with current(payload, sink):
            for row in rows:
                if batch.comments.count() >= 500:
                    break
                likes = row.get('digg_count')
                m.Comment.objects.get_or_create(batch=batch, platform_id=row['comment_id'], defaults={
                    'parent_id': row.get('parent_id') or '', 'text': row['text'][:20000],
                    'likes': likes if type(likes) is int and likes >= 0 else None, 'published_at': valid_date(row.get('created_at'))})
        save('采集评论', progress={'current': batch.comments.count(), 'total': 500 if task.input['include_replies'] else task.input['count']})

    try:
        for rows, complete in client.comment_pages(work.platform_id, task.input['count']):
            persist(rows)
            parents.extend(rows)
        if task.input['include_replies']:
            for parent in parents:
                if batch.comments.count() >= 500:
                    warning = '已达到每条作品500条评论及回复的采集上限。'
                    break
                if parent.get('reply_count') == 0:
                    continue
                for rows, _ in client.comment_pages(work.platform_id, min(20, 500 - batch.comments.count()), parent['comment_id']):
                    persist(rows)
    except CollectionError as exc:
        complete, warning = False, str(exc)
        if not batch.comments.exists():
            raise
    with current(payload, sink):
        batch.complete, batch.warning = complete, warning
        batch.save(update_fields=['complete', 'warning'])
    save('completed' if complete else 'partial', {'batch_id': str(batch.pk), 'work_id': str(work.pk), 'actual': batch.comments.count(),
        'complete': complete, 'warning': warning, 'note': '仅代表本次采集的评论样本。'})


def joint_evidence(task, payload, sink, save):
    from ..runtime import current
    from .services import start, ACTIVE
    scope = task_scope(task)
    children = []
    with current(payload, sink) as active:
        mapping = dict(active.input.get('children', {}))
        for work_id in task.input['work_ids']:
            work = m.Work.objects.select_related('account').get(pk=work_id)
            child = m.Task.objects.filter(pk=mapping.get(work_id), **scope).select_related('run').first() if mapping.get(work_id) else None
            if child is None:
                child = m.Task.objects.filter(**scope, work=work, kind='breakdown', run__status='succeeded', input__media_key=work.media_key).first()
                if not child:
                    child = start(work.account, {'kind': 'breakdown', 'work_id': str(work.pk)}, f'joint:{task.pk}:{work.pk}')
                    child.run.parent_id = task.run_id
                    child.run.node_key = str(work.pk)
                    child.run.save(update_fields=['parent', 'node_key'])
                mapping[work_id] = str(child.pk)
            children.append(child)
        active.input = {**active.input, 'children': mapping}
        active.save(update_fields=['input'])
    waiting = [str(c.run_id) for c in children if c.run and c.run.status in ACTIVE]
    states = [{'task_id': str(c.pk), 'work_id': str(c.work_id), 'status': c.run.status if c.run else 'failed', 'error': c.error} for c in children]
    save('等待视频拆解' if waiting else '联合分析', {'children': states})
    if waiting:
        sink.wait_for_children(child_run_ids=waiting, checkpoint={'task_id': str(task.pk)})
    evidence, allowed = [], set()
    for child in children:
        if not child.run or child.run.status != 'succeeded':
            continue
        segments = [{**row, 'id': f'{child.pk}:{row["id"]}'} for row in child.output.get('segments', [])]
        frames = [{'id': f'{child.pk}:{row["id"]}', 'time': row['time']} for row in child.output.get('frames', [])]
        if not segments and not child.output.get('claims'):
            continue
        allowed.update(row['id'] for row in segments + frames)
        evidence.append({'task_id': str(child.pk), 'account_id': str(child.account_id), 'work_id': str(child.work_id), 'segments': segments, 'frames': frames,
            'claims': [{**claim, 'refs': [f'{child.pk}:{ref}' for ref in claim['refs']]} for claim in child.output.get('claims', [])], 'visual_status': child.output.get('visual_status')})
    if len(evidence) < 2:
        raise ValueError('至少需要两条具有有效资料的视频；请修复失败拆解后重新发起。')
    with current(payload, sink) as active:
        active.input = {**active.input, 'joint_evidence': evidence}
        active.save(update_fields=['input'])
    return evidence, allowed, states


def execute_research(task, payload, sink, save, check, config):
    from ..runtime import current
    data, kind = task.input, task.kind
    if kind == 'voice_analysis':
        from .owned import analyze_voice
        analyze_voice(task, config, sink, save)
    elif kind == 'article':
        from .article import execute_article
        execute_article(task, payload, sink, save, config)
    elif kind == 'refresh':
        failures = []
        for index, work in enumerate(m.Work.objects.filter(pk__in=data['work_ids']).select_related('account')):
            try:
                refresh_work(task, work, LocalDTKClient(account=work.account, check=check), payload, sink)
            except CollectionError as exc:
                failures.append({'work_id': str(work.pk), 'error': str(exc)})
            save('刷新指标', progress={'current': index + 1, 'total': len(data['work_ids'])})
        if len(failures) == len(data['work_ids']):
            raise ValueError(failures[0]['error'])
        save('partial' if failures else 'completed', {'failures': failures, 'actual': len(data['work_ids']) - len(failures)})
    elif kind == 'comments':
        collect_comments(task, payload, sink, save, check)
    elif kind == 'joint':
        evidence, allowed, states = joint_evidence(task, payload, sink, save)
        result = analysis.call_claims(task, '对比各视频开头、论证、案例、表达节奏、结尾；给出共性、差异、适用条件。只引用提供的带任务前缀的片段或帧ID。缺失画面分析时不推断画面。',
            {'videos': evidence}, config, allowed, cancelled=lambda: sink.cancelled)
        save('completed', {**result, 'children': states, 'evidence': evidence})
    elif kind == 'radar':
        save('聚类选题')
        allowed = {row['id'] for row in data['evidence']}
        result = structured(task, '将作品按主题聚类，最多20个，返回 {"topics":[{"title":"主题","angle":"同题不同角度和适用条件","refs":["作品ID"]}]}。标题资料只允许初步推测。',
            {'works': radar_evidence(data['evidence']), 'previous_topic_names': data.get('previous_topics'),
             'naming_rule': '主题相同时沿用上次主题名称，只有内容方向发生变化才创建新名称。'}, config, lambda v: validate_topics_report(v, allowed), sink)
        prior = data.get('previous_topics')
        for topic in result['topics']:
            topic['is_new'] = None if prior is None else topic['title'].strip().casefold() not in {t.strip().casefold() for t in prior}
            rows = [row for row in data['evidence'] if row['id'] in topic['refs']]
            topic['account_count'] = len({r['account_id'] for r in rows})
            topic['sample_count'] = len(rows)
            from statistics import median
            topic['median_likes'] = median(values) if (values := [r['likes'] for r in rows if type(r.get('likes')) is int]) else None
        save('completed', {**result, 'coverage': data['coverage'], 'baseline': prior is None,
            'new_topic_note': '新出现表示本次主题名称未出现在上次同范围报告中，需结合原作核对。'})
    elif kind == 'needs':
        save('研究评论需求')
        allowed = {row['id'] for row in data['comments']}
        result = analysis.call_claims(task, '按反复问题、购买顾虑、争议点、未满足需求分析本次评论样本，并提出可执行选题建议。每项结论引用评论ID，不能推广为全部用户。',
            {'comments': data['comments']}, config, allowed, cancelled=lambda: sink.cancelled)
        save('completed', {**result, 'comments': data['comments'], 'sample_count': len(data['comments'])})
    elif kind == 'variants':
        save('生成候选表达')
        result = structured(task, '根据文案生成各3个开头、标题、封面短句。返回 {"hooks":[{"text":"开头","angle":"表达角度"}],"titles":[{"text":"标题","angle":"表达角度"}],"covers":[{"text":"封面短句","angle":"表达角度"}]}。只提供候选方案，不承诺效果。',
            {'content': data['content']}, config, validate_variants, sink)
        with current(payload, sink) as active:
            m.ScriptVersion.objects.get_or_create(task=active, revision=1, defaults={'content': result})
        save('completed', result)
    elif kind in ['compare', 'review']:
        save('分析样本')
        allowed = {r['account_id'] for r in data['comparison']['accounts']} if kind == 'compare' else {p['id'] for p in data['publications']}
        evidence = data['comparison'] if kind == 'compare' else [
            {**{k: p[k] for k in ['id', 'theme', 'title', 'hook']}, 'work': model_evidence(p['work']),
             'observations': len(p['trend']), 'latest': p['trend'][-1] if p['trend'] else None,
             'first': p['trend'][0] if p['trend'] else None} for p in data['publications']]
        result = analysis.call_claims(task, '比较采集样本并给出下一轮实验建议；区分观察、推测和建议。必须指出样本量、采集时间及作品年龄差异，不推断播放量、完播率、因果或未来效果。引用账号ID或发布关联ID。',
            {'samples': evidence}, config, allowed, cancelled=lambda: sink.cancelled)
        save('completed', {**result, 'comparison': evidence})
    else:
        raise ValueError('不支持的研究任务。')
