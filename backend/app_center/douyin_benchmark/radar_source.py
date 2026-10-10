"""Application-owned hotlist/search adapter; no credentials or media in results."""
from datetime import datetime, timezone
from urllib.parse import quote

HOTLIST = 'douyin.radar_hotlist'
SEARCH = 'douyin.radar_search'


def request_spec(endpoint, params, adapter, identity):
    from dtk.platforms.douyin.endpoints import DouyinAPIEndpoints
    from dtk.platforms.douyin.params import base_params
    query = base_params(adapter.profile_for(identity.fingerprint))
    if endpoint == HOTLIST:
        url = DouyinAPIEndpoints.DOUYIN_HOT_SEARCH
        query.update(detail_list='1', source='6')
    else:
        url = DouyinAPIEndpoints.VIDEO_SEARCH
        query.update(keyword=params['keyword'], offset=str(params.get('cursor') or 0), count='20',
                     search_channel='aweme_video_web', search_source='normal_search', sort_type='0',
                     publish_time='0', is_filter_search='0', query_correct_type='1', enable_history='1')
        if params.get('search_id'):
            query['search_id'] = params['search_id']
    return {'url': url, 'params': query, 'headers': dict(adapter.default_headers)}


def search_failure(payload):
    """Classify only the envelope message, never expose its free text."""
    message = str(payload.get('status_msg') or payload.get('message') or '').lower() if isinstance(payload, dict) else ''
    if any(marker in message for marker in ('登录', '登陆', 'login', 'log in')):
        return 'auth'
    return 'search_unavailable'


def number(value):
    return value if type(value) is int and value >= 0 else None


def parse_hotlist(payload, captured_at):
    rows = (payload.get('data') or {}).get('word_list')
    if not isinstance(rows, list):
        raise ValueError('invalid')
    result = []
    seen = set()
    for row in rows[:50]:
        if not isinstance(row, dict) or not isinstance(row.get('word'), str) or not row['word'].strip():
            raise ValueError('invalid')
        title = row['word'].strip()[:300]
        source_id = 'hot:' + str(row.get('sentence_id') or title)
        if source_id in seen:
            continue
        seen.add(source_id)
        result.append({'id': source_id, 'kind': 'hot', 'title': title,
                       'rank': number(row.get('position')), 'heat': number(row.get('hot_value')),
                       'url': 'https://www.douyin.com/search/' + quote(title, safe=''),
                       'captured_at': captured_at})
    return {'items': result, 'has_more': False, 'captured_at': captured_at}


def parse_search(payload, captured_at):
    rows = payload.get('data')
    if not isinstance(rows, list):
        raise ValueError('invalid')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid')
        work = row.get('aweme_info')
        # Search may also return non-work modules (suggestions, banners).
        if work is None:
            continue
        if not isinstance(work, dict):
            raise ValueError('invalid')
        platform_id = str(work.get('aweme_id') or '')
        if not platform_id.isascii() or not platform_id.isdigit():
            raise ValueError('invalid')
        stats = work.get('statistics') or {}
        author = work.get('author') or {}
        if not isinstance(stats, dict) or not isinstance(author, dict):
            raise ValueError('invalid')
        published_at = None
        stamp = number(work.get('create_time'))
        if stamp:
            try:
                published_at = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                pass
        description = work.get('desc') or ''
        if not isinstance(description, str):
            raise ValueError('invalid')
        result.append({'id': 'work:' + platform_id, 'kind': 'work', 'platform_id': platform_id,
                       'title': description[:300] or '未命名作品', 'description': description[:4000],
                       'author': str(author.get('nickname') or '')[:200], 'published_at': published_at,
                       'url': 'https://www.douyin.com/?modal_id=' + platform_id, 'captured_at': captured_at,
                       **{key: number(stats.get(field)) for key, field in
                          [('likes', 'digg_count'), ('comments', 'comment_count'),
                           ('collects', 'collect_count'), ('shares', 'share_count')]}})
    if rows and not result:
        raise ValueError('invalid')
    has_more = payload.get('has_more')
    if has_more not in (0, 1, False, True):
        raise ValueError('invalid')
    cursor = payload.get('cursor')
    log = payload.get('log_pb') or {}
    return {'items': result, 'has_more': bool(has_more), 'cursor': str(cursor) if cursor is not None else None,
            'search_id': str(log.get('impr_id') or '') if isinstance(log, dict) else '', 'captured_at': captured_at}
