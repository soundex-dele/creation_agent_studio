"""Bounded, owner-visible execution history; never store reasoning or raw tool output."""
import re
from copy import deepcopy
from django.utils import timezone

MAX_ITEMS = 100
MAX_TEXT = 2000
LABELS = {'shell': '执行读取命令', 'read': '读取文件', 'search': '搜索代码', 'list': '查看目录',
    'promotion_cite_sources': '登记源码引用', 'promotion_submit_cases': '提交素材'}


def display_text(value):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'(?i)(bearer\s+)[\w.\-]+', r'\1[已隐藏]', value)
    value = re.sub(r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|password|secret)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''', r'\1[已隐藏]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{16,}\b', '[已隐藏]', value)
    return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + '\n…（内容已截断）'


class ActivityLog:
    def __init__(self):
        self.items = []
        self.sequence = 0
        self.session = 0
        self.dropped = 0

    def snapshot(self):
        return {'items': deepcopy(self.items), 'dropped': self.dropped}

    def finish(self):
        for row in self.items:
            if row['status'] == 'running':
                row['status'] = 'stopped'
                row['updated_at'] = timezone.now().isoformat()

    def record(self, kind, payload):
        title, detail, status, key = '', '', 'completed', ''
        if kind == 'session.started':
            self.finish()
            self.session += 1
            title = 'Agent 会话已启动' if self.session == 1 else f'Agent 重新尝试（第 {self.session} 次会话）'
        elif kind == 'stage':
            title = display_text(payload.get('text'))
        elif kind in {'tool.started', 'tool.completed', 'tool.failed'}:
            name = str(payload.get('name') or '')
            title = ' / '.join(LABELS.get(part, '执行工具') for part in name.split(' / '))
            status = {'tool.started': 'running', 'tool.completed': 'completed', 'tool.failed': 'failed'}[kind]
            call_id = payload.get('tool_call_id')
            key = f'{self.session}:{str(call_id)[:160]}' if call_id else ''
            value = payload.get('input')
            if payload.get('tool_type') == 'commandExecution':
                detail = display_text(value)
            elif name == 'promotion_cite_sources' and isinstance(value, dict):
                sources = value.get('sources')
                detail = display_text('\n'.join(f"{row.get('path', '')}:{row.get('start', '')}-{row.get('end', '')}"
                    for row in (sources[:30] if isinstance(sources, list) else []) if isinstance(row, dict)))
            elif name == 'promotion_submit_cases' and isinstance(value, dict):
                cases = value.get('cases')
                detail = display_text(value.get('insufficient_reason') or '\n'.join(
                    str(row.get('title', '')) for row in (cases[:12] if isinstance(cases, list) else []) if isinstance(row, dict)))
        elif kind == 'agent.item' and payload.get('type') == 'agentMessage' and payload.get('completed'):
            title, detail = 'Agent 说明', display_text(payload.get('text'))
            key = f"{self.session}:message:{str(payload.get('id', ''))[:160]}"
        elif kind == 'agent.plan':
            title = '更新执行计划'
            detail = display_text('\n'.join(str(step.get('step', '')) for step in payload.get('plan', [])[:20] if isinstance(step, dict)))
        if not title or (kind in {'agent.item', 'agent.plan'} and not detail):
            return None
        previous = next((row for row in self.items if key and row.get('key') == key), None)
        if previous:
            # Some completion notifications omit their original command.
            detail = detail or previous['detail']
            if previous['status'] == status and previous['detail'] == detail:
                return None
            previous.update(status=status, detail=detail, updated_at=timezone.now().isoformat())
            return previous
        self.sequence += 1
        now = timezone.now().isoformat()
        row = dict(id=str(self.sequence), key=key, title=title, detail=detail, status=status,
                   created_at=now, updated_at=now)
        self.items.append(row)
        if len(self.items) > MAX_ITEMS:
            self.items.pop(0)
            self.dropped += 1
        return row
