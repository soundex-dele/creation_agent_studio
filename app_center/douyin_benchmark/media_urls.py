"""Shared media preference for the standalone DTK script and Django app.

Prefer the v11 CDN reported playable in this deployment. This is an ordering
policy, not a claim that other CDNs are universally unavailable. Signed URLs
must remain byte-for-byte unchanged: never substitute one hostname for another.
"""
import re
from urllib.parse import urlsplit


# DTK src/dtk/media/domains.py DOUYIN_MEDIA_DOMAINS, plus the two media
# networks already supported by this app. Kept Python 3.11 compatible; source
# integration tests check that the pinned DTK list remains covered.
DOUYIN_MEDIA_DOMAINS = frozenset({
    "douyinvod.com", "zjcdn.com", "douyinpic.com", "douyinstatic.com",
    "iesdouyin.com", "douyin.com", "bytecdn.cn", "byteimg.com", "pstatp.com",
    "ibyteimg.com", "amemv.com", "ixigua.com", "bytedance.com",
    "douyincdn.com", "ibytedtos.com",
})


def prioritize_video_urls(urls):
    def preferred(url):
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            return (parsed.scheme in ("http", "https") and not parsed.username and not parsed.password
                and parsed.port in (None, 443 if parsed.scheme == "https" else 80)
                and re.fullmatch(r"v11(?:-[a-z0-9]+)*\.douyinvod\.com", host) is not None)
        except (TypeError, ValueError):
            return False

    unique = list(dict.fromkeys(url for url in urls if isinstance(url, str) and url))
    return sorted(unique, key=lambda url: not preferred(url))
