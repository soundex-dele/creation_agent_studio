from django.conf import settings
from django.core.checks import Error, register
from pathlib import Path


@register()
def channel_configuration(app_configs, **kwargs):
    errors = []
    backend = settings.CHANNEL_LAYERS.get('default', {}).get('BACKEND', '')
    if settings.COMMUNITY_CHAT_WORKERS > 1 and backend.endswith('InMemoryChannelLayer'):
        errors.append(Error('社区聊天多进程部署必须启用 Redis channel layer。', id='community_chat.E001'))
    if Path(settings.COMMUNITY_CHAT_ROOT).resolve().is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
        errors.append(Error('聊天文件目录不能放在公开 MEDIA_ROOT 中。', id='community_chat.E002'))
    if '*' in settings.COMMUNITY_CHAT_ALLOWED_ORIGINS:
        errors.append(Error('聊天 WebSocket 必须配置明确的允许来源，不能使用 *。', id='community_chat.E003'))
    return errors
