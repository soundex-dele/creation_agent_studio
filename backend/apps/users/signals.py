"""Provision directories for new users and backfill existing installations."""
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from core.user_directories import user_directory
from .models import User


@receiver(post_save, sender=User)
def provision_user_directory(sender, instance, raw=False, **kwargs):
    if not raw and instance.is_active:
        user_directory(instance)


@receiver(post_migrate)
def provision_existing_user_directories(sender, **kwargs):
    if sender.name == 'apps.users':
        for user in User.objects.filter(is_active=True).iterator():
            user_directory(user)
