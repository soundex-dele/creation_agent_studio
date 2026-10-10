"""Model-directed, cancellable exploration of an immutable repository snapshot."""
from collections import OrderedDict
import re

from .content import text, strings
from .retrieval import chunks
from .sources import limits


EXPLORATION_INSTRUCTION = '''你正在为仓库策划5个有源码依据的选题，自主决定探索路径与结束时机。
探索不限制轮次。有用户方向时围绕该方向寻找资料，否则探索不同的内容角度。
你通过返回JSON动作请求服务器读取冻结的仓库快照；不要调用外部工具、联网或执行代码。
每次只返回一个动作，可附 notes 字符串（最多8000字）：记下已核实事实、证据编号与后续待查线索，
作为下一轮替换后的工作笔记。笔记不能替代源码证据，不需要输出思考过程。
可用动作：
1. {"action":"list","prefix":"目录前缀，根目录为空","offset":0}：分页列出文件，每页100项。
2. {"action":"search","query":"关键词或路径","offset":0}：在整个快照的可读片段中搜索，每页30项。
3. {"action":"read","path":"快照中的精确文件路径","start":1}：读取包含该行的80行片段；按返回的next_start继续读。
4. {"action":"finish","evidence_ids":["e1","e2"]}：确认探索足够，选出生成5个选题需要的已读证据。
结束时可以引用已经移出当前上下文的已读证据，服务器会从快照恢复；不能引用未读片段。
一次finish最多150个证据编号，证据文本总长度不能超过给定的上下文容量；超出时重新筛选最相关证据。
上下文中的源码是最近读取的窗口，旧片段会移出以腾出空间，累计探索不受该窗口容量限制。
根目录可能不止一页；搜索无匹配或重复读取时可更换查询、翻页、查看相邻代码，或自行决定结束。
不必为凑轮次而读取无关文件，也不要将所有片段已读或一次搜索无结果误解为必须结束。
只看到文档、测试、接口或TODO不能声称功能已实现；仅静态阅读，不能声称实测效果。
本阶段不生成选题正文；结束后由选题生成阶段整理结果。'''


def explore(files, model, progress, direction='', check=lambda: None):
    """No round or cumulative-read cap; only the model (or cancellation/error) ends it."""
    all_chunks = chunks(files)
    by_id = {row['id']: row for row in all_chunks}
    by_location = {(row['path'], row['start']): row for row in all_chunks}
    paths = sorted(files)
    bound = limits()['analysis_chars']
    if bound <= 0:
        raise ValueError('源码上下文容量必须大于0。')
    seen, window = {}, OrderedDict()
    window_chars, rounds = 0, 0
    notes, feedback = '', {'action': 'initial', 'files': paths[:100], 'next_offset': 100 if len(paths) > 100 else None}

    def remember(row):
        nonlocal window_chars
        size = len(row['quote'])
        if size > bound:
            raise ValueError('该片段超过当前上下文容量，请选择其他片段或调整服务端上下文容量。')
        if row['id'] in window:
            window.move_to_end(row['id'])
        else:
            while window and window_chars + size > bound:
                _, removed = window.popitem(last=False)
                window_chars -= len(removed['quote'])
            window[row['id']] = row
            window_chars += size
        seen[row['id']] = row

    def coverage(selected):
        total = sum((len(file['text'].splitlines()) + 79) // 80 for file in files.values())
        return {'files_read': len({row['path'] for row in seen.values()}), 'files_total': len(files),
            'chunks_read': len(seen), 'chunks_total': total,
            'characters_read': sum(len(row['quote']) for row in seen.values()),
            'evidence_characters': sum(len(row['quote']) for row in selected.values()),
            'exploration_rounds': rounds, 'incomplete': len(seen) < total,
            'note': 'AI自主决定结束探索；读取范围按累计去重片段统计。仅静态阅读，未运行验证，超长片段与未读内容尚待核实。'}

    # Start from entrypoints, but leave later file choice and stopping to the model.
    def priority(row):
        path = row['path'].lower()
        return (not any(key in path for key in ('readme', 'package.json', 'application.yaml', 'routes', 'urls.py', 'main.', 'app.', 'docs/')),
                row['start'], path)
    for index, row in enumerate(sorted(all_chunks, key=priority)):
        if index % 1024 == 0:
            check()
        if window_chars + len(row['quote']) <= bound // 3:
            remember(row)
    if not all_chunks:
        return {}, coverage({})

    while True:
        check()
        rounds += 1
        progress(f'自主探索源码（第{rounds}轮，累计读取{len(seen)}个片段）')
        data = {'方向': direction, '文件总数': len(files), '可读片段总数': len(all_chunks),
            '上下文容量': bound, '累计已读片段数': len(seen), '工作笔记': notes,
            '上次动作结果': feedback, '当前源码窗口': list(window.values())}
        try:
            response = model(EXPLORATION_INSTRUCTION, data)
            check()
            if not isinstance(response, dict):
                raise ValueError('探索动作必须是JSON对象。')
            action = response.get('action')
            if 'notes' in response:
                notes = text(response['notes'], '探索笔记', 8000)
            if action == 'finish':
                ids = list(dict.fromkeys(strings(response.get('evidence_ids'), '最终证据', 150)))
                if any(key not in seen for key in ids):
                    raise ValueError('结束探索只能选用已经读取的证据编号；请先读取所需源码。')
                selected = {key: by_id[key] for key in ids}
                if sum(len(row['quote']) for row in selected.values()) > bound:
                    raise ValueError('所选最终证据超过上下文容量，请精简证据列表；仍可继续探索。')
                progress('AI已完成源码探索，整理选题依据')
                return selected, coverage(selected)
            if action in {'list', 'search'}:
                offset = response.get('offset', 0)
                if type(offset) is not int or offset < 0:
                    raise ValueError('offset必须为非负整数。')
                if action == 'list':
                    prefix = text(response.get('prefix', ''), '目录前缀', 2000)
                    matches = [path for path in paths if path.startswith(prefix)]
                    feedback = {'action': action, 'files': matches[offset:offset + 100], 'total': len(matches),
                        'next_offset': offset + 100 if offset + 100 < len(matches) else None}
                else:
                    query = text(response.get('query'), '搜索词', 500, False)
                    terms = [word.lower() for word in re.findall(r'[\w./-]+', query) if word]
                    scored = []
                    for index, row in enumerate(all_chunks):
                        if index % 1024 == 0:
                            check()
                        score = sum(5 * (term in row['path'].lower()) + (term in row['quote'].lower()) for term in terms)
                        if score:
                            scored.append((score, row))
                    matches = [row for _, row in sorted(scored, key=lambda item: -item[0])]
                    feedback = {'action': action, 'query': query, 'matches': [
                        {key: row[key] for key in ('id', 'path', 'start', 'end')} for row in matches[offset:offset + 30]],
                        'total': len(matches), 'next_offset': offset + 30 if offset + 30 < len(matches) else None}
            elif action == 'read':
                path = text(response.get('path'), '文件路径', 2000, False)
                start = response.get('start', 1)
                if path not in files:
                    raise ValueError('文件不在当前源码快照中，请列目录或搜索后使用精确路径。')
                if type(start) is not int or start < 1:
                    raise ValueError('start必须为正整数行号。')
                line = ((start - 1) // 80) * 80 + 1
                row = by_location.get((path, line))
                if row is None:
                    raise ValueError('该范围没有可读片段（超出文件行数或片段超过12000字符），可读取其他范围。')
                already_read = row['id'] in seen
                remember(row)
                total_lines = len(files[path]['text'].splitlines())
                feedback = {'action': action, 'id': row['id'], 'path': path, 'already_read': already_read,
                    'next_start': row['end'] + 1 if row['end'] < total_lines else None}
            else:
                raise ValueError('请选择list、search、read或finish动作。')
        except (ValueError, KeyError, TypeError) as exc:
            # Tool feedback is not an exploration stopping rule. The next turn may
            # choose another path, repair its request, or finish explicitly.
            feedback = {'error': str(exc)}
        check()
