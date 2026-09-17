"""Lifecycle cleanup for files owned by conversation attachments."""
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
    transaction.on_commit(lambda: storage.delete(name))
