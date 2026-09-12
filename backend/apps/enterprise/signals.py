from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

from apps.users.models import User
from .models import GovernancePolicy, Membership, Organization, QuotaPolicy
from .tenancy import provision_single_tenant_user, single_tenant_mode_enabled


@receiver(post_save, sender=User)
def create_personal_organization(sender, instance, created, **kwargs):
    if not created:
        return
    if single_tenant_mode_enabled():
        provision_single_tenant_user(instance)
        return
    base = slugify(instance.username)[:70] or f'user-{instance.pk}'
    slug = f'{base}-{instance.pk}'
    org = Organization.objects.create(
        name=f'{instance.username} Workspace', slug=slug, owner=instance)
    Membership.objects.create(organization=org, user=instance,
                              role=Membership.Role.OWNER)
    QuotaPolicy.objects.create(organization=org)
    GovernancePolicy.objects.create(organization=org)
