"""Conservative metadata verification. No audio or arbitrary URL fetching."""
import hashlib
import re
import time
from urllib.parse import urlparse
import requests
from django.core.cache import cache
from django.utils import timezone
from .domain import normalized, title_version
from .models import CatalogGate

ENDPOINT = 'https://itunes.apple.com/search'


def search(term, country, cancelled=lambda: False):
    key = 'song:itunes:' + hashlib.sha256(f'{country}:{term}'.encode()).hexdigest()
    existing = cache.get(key)
    if existing is not None:
        return existing
    # A DB compare-and-set works across subprocess workers even with Local's
    # in-process cache. Only this public service timestamp is shared across tenants.
    CatalogGate.objects.get_or_create(name='itunes')
    deadline = time.monotonic() + 8
    while not CatalogGate.objects.filter(name='itunes', next_at__lte=time.time()).update(next_at=time.time() + 3.1):
        if cancelled():
            raise InterruptedError('任务已取消。')
        if time.monotonic() >= deadline:
            raise RuntimeError('目录检索繁忙。')
        time.sleep(0.2)
    if cancelled():
        raise InterruptedError('任务已取消。')
    with requests.get(ENDPOINT, params={'term': term, 'country': country, 'entity': 'song', 'limit': 20},
                      timeout=(4, 8), allow_redirects=False, stream=True,
                      headers={'User-Agent': 'CreationAgentStudio-SongCurator/1.0'}) as response:
        if response.status_code != 200:
            raise RuntimeError('目录服务暂不可用。')
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 1024 * 1024:
                raise ValueError('目录响应过大。')
        import json
        value = json.loads(content)
    rows = value.get('results')
    if not isinstance(rows, list):
        raise ValueError('目录响应无效。')
    rows = [row for row in rows[:20] if isinstance(row, dict)]
    cache.set(key, rows, timeout=86400 if rows else 600)
    return rows


def verify(track, language='follow', cancelled=lambda: False):
    result = {'status': 'not_found', 'source': 'iTunes', 'checkedAt': timezone.now().isoformat()}
    if not track.get('artist'):
        return {**result, 'status': 'ambiguous'}
    countries = ['HK', 'US'] if language in ('zh', 'ja-ko') or (language in ('follow', 'any') and re.search(r'[\u3000-\u9fff]', track['title'] + track['artist'])) else ['US', 'HK']
    unavailable = False
    for country in countries:
        if cancelled():
            raise InterruptedError('任务已取消。')
        try:
            rows = search(f"{track['title']} {track['artist']}", country, cancelled)
            matches = []
            for row in rows:
                if not isinstance(row.get('trackName'), str) or not isinstance(row.get('artistName'), str):
                    continue
                if title_version(row['trackName']) != title_version(track['title'], track.get('version', '')):
                    continue
                if normalized(row['artistName']) != normalized(track['artist']):
                    continue
                if track.get('album') and normalized(row.get('collectionName', '')) != normalized(track['album']):
                    continue
                url = row.get('trackViewUrl', '')
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.hostname not in ('music.apple.com', 'itunes.apple.com') or not row.get('trackId'):
                    continue
                matches.append(row)
            unique = {row['trackId']: row for row in matches}
            if len(unique) > 1:
                return {**result, 'status': 'ambiguous', 'country': country}
            if unique:
                row = next(iter(unique.values()))
                return {**result, 'status': 'verified', 'catalogId': str(row['trackId']),
                        'url': row['trackViewUrl'], 'country': country}
        except InterruptedError:
            raise
        except (requests.RequestException, ValueError, RuntimeError, TypeError):
            unavailable = True
    return {**result, 'status': 'unavailable' if unavailable else 'not_found'}
