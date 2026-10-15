from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MediaAsset, Recording, VideoDeliverable


@receiver(post_delete, sender=MediaAsset)
def delete_asset_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=Recording)
def delete_recording_file(sender, instance, **kwargs):
    if instance.audio:
        instance.audio.delete(save=False)


@receiver(post_delete, sender=VideoDeliverable)
def delete_deliverable_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
