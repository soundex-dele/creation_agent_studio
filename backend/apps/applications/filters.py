"""Filters for applications app."""
import django_filters
from .models import Application


class ApplicationFilter(django_filters.FilterSet):
    """应用过滤器"""
    category = django_filters.CharFilter(
        field_name='category__slug',
        lookup_expr='iexact',
        help_text='按分类 slug 过滤',
    )

    class Meta:
        model = Application
        fields = ['category', 'kind']
