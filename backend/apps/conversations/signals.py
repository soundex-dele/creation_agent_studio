"""Lifecycle cleanup for files owned by conversation attachments."""
from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MessageAttachment


@receiver(post_delete, sender=MessageAttachment)
def delete_attachment_file_after_commit(sender, instance, **kwargs):
    if not instance.file or not instance.file.name:
        return
    storage = instance.file.storage
    name = instance.file.name

    def delete_if_unreferenced():
        try:
            Problem = apps.get_model("study_with_method", "Problem")
        except LookupError:
            Problem = None
        if Problem is not None and Problem.objects.filter(source_image=name).exists():
            return
        storage.delete(name)

    transaction.on_commit(delete_if_unreferenced)
