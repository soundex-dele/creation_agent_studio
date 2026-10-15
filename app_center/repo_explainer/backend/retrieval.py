"""Bounded retrieval over an immutable snapshot, without executing repository code."""
import re
from modules.platform_api.repository_sources import limits
from .content import strings


def chunks(files):
    result = []
    for path, file in sorted(files.items()):
        lines = file['text'].splitlines()
        for start in range(0, len(lines), 80):
            # Very long lines remain in the snapshot but are excluded from model context.
            excerpt = '\n'.join(lines[start:start + 80])
            if len(excerpt) > 12000:
                continue
            result.append({'id': f'e{len(result) + 1}', 'path': path, 'start': start + 1,
                           'end': min(start + 80, len(lines)), 'quote': excerpt})
    return result


def retrieve(files, model, progress, direction=""):
    all_chunks = chunks(files)
    bound = limits()['analysis_chars']
    chosen, used = {}, 0
    def add(rows):
        nonlocal used
        for row in rows:
            if row['id'] in chosen or used + len(row['quote']) > bound:
                continue
            chosen[row['id']] = row
            used += len(row['quote'])
    def priority(c):
        p = c['path'].lower()
        return (not any(s in p for s in ('readme', 'package.json', 'application.yaml', 'routes', 'urls.py', 'main.', 'app.', 'docs/')), c['start'], p)
    initial = sorted(all_chunks, key=priority)
    initial_budget = bound // 3
    for c in initial:
        if used + len(c['quote']) <= initial_budget:
            add([c])
    for index in range(limits()['rounds']):
        progress(f'追踪源码证据（{index + 1}/{limits()["rounds"]}）')
        response = model('结合入口与目录识别值得介绍的内容；有用户方向时优先追踪该方向，提出用于核实实现的路径或关键词。只返回 {"queries":["短关键词或路径"]}，最多12项。',
            {'方向': direction, '目录': list(files)[:5000], '已读片段': list(chosen.values())})
        queries = strings(response.get('queries', []), '检索查询', 12)
        terms = [t.lower() for q in queries for t in re.findall(r'[\w./-]+', q) if len(t) > 1]
        if not terms or used >= bound:
            break
        candidates = sorted((c for c in all_chunks if c['id'] not in chosen),
            key=lambda c: -sum(5 * (t in c['path'].lower()) + (t in c['quote'].lower()) for t in terms))
        add([c for c in candidates[:30] if any(t in c['path'].lower() or t in c['quote'].lower() for t in terms)])
    coverage = {'files_read': len({c['path'] for c in chosen.values()}), 'files_total': len(files),
        'chunks_read': len(chosen), 'chunks_total': sum((len(f['text'].splitlines()) + 79) // 80 for f in files.values()), 'characters_read': used,
        'incomplete': len(chosen) < sum((len(f['text'].splitlines()) + 79) // 80 for f in files.values()),
        'note': '仅静态分析所列片段；未读取内容、超长片段与功能尚待核实。'}
    return chosen, coverage
