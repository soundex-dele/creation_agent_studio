from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from . import knowledge as k, models as m
from .research_views import WorkspaceMixin
from .views import BaseView
from .services import Conflict


class KnowledgeCardsView(WorkspaceMixin, BaseView):
    def cards(self):
        return m.CreationKnowledgeCard.objects.filter(**self.scope(), is_deleted=False).select_related('document')

    def get(self, request, **kwargs):
        cards = self.cards()
        if kwargs.get('card_id'):
            return Response(k.serialize_card(get_object_or_404(cards, pk=kwargs['card_id'])))
        query = request.query_params.get('search', '')[:200]
        if query:
            cards = cards.filter(Q(title__icontains=query) | Q(text__icontains=query) | Q(application_notes__icontains=query))
        if request.query_params.get('category'):
            cards = cards.filter(category=request.query_params['category'])
        if request.query_params.get('tag'):
            cards = cards.filter(pk__in=[row.pk for row in cards if request.query_params['tag'] in row.tags])
        pager = Paginator(cards, 20)
        return Response({'count': pager.count, 'results': [k.serialize_card(c) for c in pager.get_page(request.query_params.get('page', 1))]})

    @transaction.atomic
    def patch(self, request, **kwargs):
        if not kwargs.get('card_id'):
            raise MethodNotAllowed('PATCH')
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        card = get_object_or_404(self.cards().select_for_update(), pk=kwargs['card_id'])
        if request.data.get('revision') != card.revision:
            raise Conflict('知识已更新，请刷新后重试；当前编辑内容仍可保留。')
        fields = k.CardFields(data=request.data)
        fields.is_valid(raise_exception=True)
        for key, value in fields.validated_data.items():
            setattr(card, key, value)
        card.revision += 1
        card.save()
        k.queue_index(card, request.user)
        return Response(k.serialize_card(card))

    @transaction.atomic
    def delete(self, request, **kwargs):
        if not kwargs.get('card_id'):
            raise MethodNotAllowed('DELETE')
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        card = get_object_or_404(self.cards().select_for_update(), pk=kwargs['card_id'])
        card.is_deleted = True
        card.save(update_fields=['is_deleted', 'updated_at'])
        card.document.is_deleted = True
        card.document.save(update_fields=['is_deleted', 'updated_at'])
        return Response(status=204)


class KnowledgeConfirmView(WorkspaceMixin, BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        scope = self.scope()
        fields = k.ConfirmInput(data=request.data)
        fields.is_valid(raise_exception=True)
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        return Response({'cards': k.confirm_cards(scope, request.user, fields.validated_data)})


class KnowledgeRecommendView(WorkspaceMixin, BaseView):
    def get(self, request, **kwargs):
        query = serializers.CharField(max_length=6000, allow_blank=True).run_validation(request.query_params.get('query', ''))
        return Response({'results': k.recommend(self.scope(), query)})


class KnowledgeRetryView(KnowledgeCardsView):
    @transaction.atomic
    def post(self, request, **kwargs):
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        card = get_object_or_404(self.cards().select_for_update(), pk=kwargs['card_id'])
        if card.document.status == 'failed':
            k.queue_index(card, request.user)
        return Response(k.serialize_card(card))


class KnowledgeSharesView(KnowledgeCardsView):
    http_method_names = ['get', 'post', 'head', 'options']

    def get(self, request, **kwargs):
        from .organization_knowledge import share_data
        from modules.tenancy.permissions import ROLE_LEVEL
        card = get_object_or_404(self.cards(), pk=kwargs['card_id'])
        role = getattr(getattr(request, 'organization_membership', None), 'role', '')
        return Response({'can_share': ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL['developer'] and getattr(request.user, 'role', '') != 'auditor',
                         'results': [share_data(row) for row in card.shares.select_related('knowledge_base', 'document')]})

    def post(self, request, **kwargs):
        from .organization_knowledge import ShareInput, publish
        fields = ShareInput(data=request.data)
        fields.is_valid(raise_exception=True)
        card = get_object_or_404(self.cards(), pk=kwargs['card_id'])
        return Response(publish(card, request.user, fields.validated_data))
