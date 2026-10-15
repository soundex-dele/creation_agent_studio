"""Load trusted application contributions without importing business modules here."""
from functools import lru_cache
from importlib import import_module
import logging

from django.conf import settings
from .discovery import discover_packages
from modules.platform_api.extensions import ApplicationContributions

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _load(root, registry_hash):
    packages, _ = discover_packages(root)
    providers = []
    for package in packages:
        entrypoint = package.manifest.spec.backend.extensions
        if entrypoint:
            module, attribute = entrypoint.rsplit('.', 1)
            provider = getattr(import_module(module), attribute)
            if not isinstance(provider, ApplicationContributions):
                raise ValueError(f'{entrypoint} must export ApplicationContributions')
            providers.append(provider)
    return tuple(providers)


def contributions():
    return _load(str(settings.APP_CENTER_ROOT), settings.APP_CENTER_REGISTRY_HASH)


def run_access(user, root):
    """None means unclaimed; every applicable policy must allow access."""
    decisions = []
    try:
        for provider in contributions():
            hook = getattr(provider, 'run_access', None)
            if hook:
                decision = hook(user, root)
                if decision is not None:
                    decisions.append(decision is True)
    except Exception:
        logger.exception('Application access policy failed')
        return False
    return all(decisions) if decisions else None


def knowledge_context(document):
    context = {}
    for provider in contributions():
        hook = getattr(provider, 'knowledge_context', None)
        if hook:
            values = hook(document) or {}
            if context.keys() & values.keys():
                raise ValueError('Conflicting knowledge context contributions')
            context.update(values)
    return context


def case_navigation(case, user):
    for provider in contributions():
        hook = getattr(provider, 'case_navigation', None)
        if hook:
            value = hook(case, user)
            if value is not None:
                return value
    return None


def case_targets(source, user, organization_id):
    for provider in contributions():
        hook = getattr(provider, 'case_targets', None)
        if hook:
            value = hook(source, user, organization_id)
            if value is not None:
                return value
    return []


def dispatch_scheduled():
    for provider in contributions():
        hook = getattr(provider, 'dispatch_scheduled', None)
        if hook:
            try:
                hook()
            except Exception:
                logger.exception('Application scheduler pass failed')


def check_conversation_access(conversation, user):
    # Permission failures propagate; never continue with partially checked access.
    for provider in contributions():
        hook = provider.conversation_access
        if hook:
            hook(conversation, user)


def conversation_queryset(queryset):
    for provider in contributions():
        if provider.conversation_queryset:
            queryset = provider.conversation_queryset(queryset)
    return queryset


def prepare_conversation_message(conversation, user, message, context):
    for provider in contributions():
        if provider.prepare_conversation_message:
            message = provider.prepare_conversation_message(conversation, user, message, context)
    return message


def call_unique_contribution(name, *args, **kwargs):
    from rest_framework.exceptions import ValidationError
    hooks = [getattr(provider, name) for provider in contributions() if getattr(provider, name)]
    if len(hooks) != 1:
        raise ValidationError({'non_field_errors': [f'Expected one provider for {name}; found {len(hooks)}.']})
    return hooks[0](*args, **kwargs)
