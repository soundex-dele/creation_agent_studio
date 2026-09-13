from django.db import models

from apps.users.models import User
from modules.tenancy.models import TenantOwnedQuerySet


class TemplateCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, max_length=100)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']
        db_table = 'template_categories'

    def __str__(self):
        return self.name


class Template(models.Model):
    """A real-world content case together with its reusable analysis."""

    CONTENT_TYPE_CHOICES = [
        ('article', '文章'),
        ('social_post', '社交媒体图文'),
        ('video_script', '短视频脚本'),
        ('brand_story', '品牌故事'),
        ('podcast', '播客文稿'),
        ('product_analysis', '产品分析'),
        ('other', '其他'),
    ]
    COPYRIGHT_MODE_CHOICES = [
        ('link_only', '仅保留链接'),
        ('excerpt', '摘要与引用'),
        ('authorized', '已获授权'),
        ('owned', '自有内容'),
    ]
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('review', '待审核'),
        ('published', '已发布'),
        ('archived', '已归档'),
    ]

    category = models.ForeignKey(
        TemplateCategory, on_delete=models.CASCADE, related_name='templates')
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    thumbnail = models.URLField(blank=True)
    content_type = models.CharField(
        max_length=30, choices=CONTENT_TYPE_CHOICES, default='article')
    source_title = models.CharField(max_length=300, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    source_author = models.CharField(max_length=200, blank=True)
    source_platform = models.CharField(max_length=100, blank=True)
    source_published_at = models.DateField(null=True, blank=True)
    source_excerpt = models.TextField(blank=True)
    source_content = models.TextField(blank=True)
    recommended_reason = models.TextField(blank=True)
    reusable_patterns = models.JSONField(default=list, blank=True)
    copyright_mode = models.CharField(
        max_length=20, choices=COPYRIGHT_MODE_CHOICES, default='link_only')
    source_snapshot_at = models.DateTimeField(null=True, blank=True)
    word_count = models.PositiveIntegerField(default=0)
    reading_time_minutes = models.PositiveIntegerField(default=0)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    is_featured = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='templates')
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='templates'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=0)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        ordering = ['-is_featured', '-updated_at']
        db_table = 'templates'

    def __str__(self):
        return self.title


class TemplateAnalysisSection(models.Model):
    SECTION_TYPE_CHOICES = [
        ('hook', '开头钩子'),
        ('conflict', '核心冲突'),
        ('structure', '内容结构'),
        ('technique', '表达技巧'),
        ('evidence', '论据与案例'),
        ('rhythm', '叙事节奏'),
        ('conversion', '转化设计'),
        ('reusable_pattern', '可复用点'),
        ('limitations', '适用边界'),
        ('other', '其他'),
    ]

    template = models.ForeignKey(
        Template, on_delete=models.CASCADE, related_name='analysis_sections')
    section_type = models.CharField(
        max_length=30, choices=SECTION_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200)
    content = models.TextField()
    evidence_quote = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        db_table = 'template_analysis_sections'

    def __str__(self):
        return f'{self.template.title} - {self.title}'
