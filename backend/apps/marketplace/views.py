from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Count, Avg
from .models import TemplateReview, TemplateComment, UserFavorite
from .serializers import TemplateReviewSerializer, TemplateCommentSerializer, UserFavoriteSerializer
from apps.templates.models import Template
from apps.templates.serializers import TemplateListSerializer

class TemplateReviewViewSet(viewsets.ModelViewSet):
    serializer_class = TemplateReviewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TemplateReview.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class TemplateCommentViewSet(viewsets.ModelViewSet):
    serializer_class = TemplateCommentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        template_id = self.request.query_params.get('template')
        queryset = TemplateComment.objects.filter(user=self.request.user)
        if template_id:
            queryset = queryset.filter(template_id=template_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class UserFavoriteViewSet(viewsets.ModelViewSet):
    serializer_class = UserFavoriteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserFavorite.objects.filter(user=self.request.user).select_related('template')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class MarketViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def trending(self, request):
        templates = Template.objects.filter(status='published').annotate(
            review_count=Count('reviews'), avg_rating=Avg('reviews__rating')
        ).order_by('-view_count', '-avg_rating')[:20]
        serializer = TemplateListSerializer(templates, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def recommended(self, request):
        favorite_ids = request.user.favorites.values_list('template_id', flat=True)
        templates = Template.objects.filter(status='published').exclude(
            id__in=favorite_ids).order_by('-is_featured', '-view_count')[:10]
        serializer = TemplateListSerializer(templates, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def search(self, request):
        query = request.query_params.get('q', '')
        if not query:
            return Response({'detail': 'Please provide search keyword'}, status=status.HTTP_400_BAD_REQUEST)
        templates = Template.objects.filter(
            Q(title__icontains=query) | Q(summary__icontains=query) | Q(tags__icontains=query),
            status='published'
        )[:20]
        serializer = TemplateListSerializer(templates, many=True)
        return Response(serializer.data)
