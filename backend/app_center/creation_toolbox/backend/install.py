"""Idempotent installation hook for Creation Toolbox."""


def install(*, organization, application):
    from .models import CreationWorkspace

    CreationWorkspace.objects.update_or_create(
        application=application,
        defaults={
            "organization": organization,
            "name": "创作工具箱",
            "storage_mode": "managed",
            "audio_sample_rate": 44100,
            "transcription_language": "zh-CN",
        },
    )

