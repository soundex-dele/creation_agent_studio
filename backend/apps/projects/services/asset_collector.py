"""
Auto-collect generated assets (images / text) from an assistant message into the
conversation's workspace (Project).

Called by the conversations app after an assistant reply is persisted, so that
anything the model produced — image URLs or substantial text — lands in the
workspace's asset panel automatically.
"""

from core.observability import log_operation
import re
import logging

from apps.projects.models import ProjectAsset

logger = logging.getLogger(__name__)

# Markdown image syntax:  ![alt](url)   (url may not contain whitespace or closing paren)
_MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)')
# Bare image URLs ending in a known image extension
_BARE_IMAGE_RE = re.compile(
    r'(https?://[^\s)"\]]+\.(?:png|jpe?g|webp|gif|bmp|svg))',
    re.IGNORECASE,
)

_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg')


def _extract_image_urls(content):
    urls = []
    seen = set()
    for pattern in (_MD_IMAGE_RE, _BARE_IMAGE_RE):
        for url in pattern.findall(content):
            # Skip things that are clearly markdown link targets wrapped around an image ext
            clean = url.strip().rstrip('.,);]')
            if clean in seen:
                continue
            seen.add(clean)
            urls.append(clean)
    return urls


def _derive_image_name(url):
    tail = url.rsplit('/', 1)[-1].split('?')[0]
    return tail[:180] or 'image'


def _derive_text_name(content):
    for line in content.splitlines():
        stripped = line.strip(' #>*-`')
        if stripped:
            return stripped[:60]
    return '文本内容'


@log_operation
def collect_assets_from_message(project, conversation, message, output_type=''):
    """Create/refresh ProjectAsset rows for images and text found in ``message``.

    Idempotent: image assets dedupe by (project, url); text assets dedupe by
    metadata.message_id. Safe to call on every assistant reply.
    """
    if project is None or message is None:
        return []

    content = message.content or ''
    if not content.strip():
        return []

    process_id = getattr(conversation, 'process_id', '') or ''
    provenance = {
        'conversation_id': getattr(conversation, 'id', None),
        'message_id': getattr(message, 'id', None),
        'process_id': process_id,
        'output_type': output_type or '',
    }
    created = []

    # ── Images ───────────────────────────────────────────────
    for url in _extract_image_urls(content):
        asset, was_created = ProjectAsset.objects.get_or_create(
            project=project,
            url=url,
            asset_type='image',
            defaults={
                'name': _derive_image_name(url),
                'metadata': {**provenance, 'source_url': url},
            },
        )
        if was_created:
            created.append(asset)

    # ── Text (one asset per message, deduped by message_id) ──
    if provenance.get('message_id') is not None:
        existing = ProjectAsset.objects.filter(
            project=project,
            asset_type='text',
            metadata__message_id=provenance['message_id'],
        ).first()
        if existing is None:
            asset = ProjectAsset.objects.create(
                project=project,
                asset_type='text',
                name=_derive_text_name(content),
                url='',
                content=content,
                metadata=provenance,
            )
            created.append(asset)

    if created:
        logger.info(
            "collect_assets_from_message: project=%s conversation=%s message=%s -> %d assets",
            project.id, provenance.get('conversation_id'), provenance.get('message_id'), len(created),
        )
    return created
