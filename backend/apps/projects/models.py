from django.db import models
from apps.users.models import User

class Project(models.Model):
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('active', '进行中'),
        ('completed', '已完成'),
        ('archived', '已归档'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='projects'
    )
    application = models.ForeignKey(
        'applications.Application', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='projects')
    workflow = models.ForeignKey(
        'workflows.Workflow', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='projects')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    structure = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    thumbnail = models.URLField(blank=True)
    working_directory = models.CharField(max_length=1000, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        db_table = 'projects'
        constraints = [models.CheckConstraint(
            check=(models.Q(application__isnull=True) |
                   models.Q(workflow__isnull=True)),
            name='project_has_single_origin')]

    def __str__(self):
        return self.title

class ProjectAsset(models.Model):
    ASSET_TYPE_CHOICES = [
        ('video', '视频'),
        ('audio', '音频'),
        ('image', '图片'),
        ('text', '文本'),
        ('other', '其他'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='assets')
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPE_CHOICES)
    name = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    file = models.FileField(upload_to='project_assets/%Y/%m/', blank=True)
    # For text assets (no URL), the generated content is stored here.
    content = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']
        db_table = 'project_assets'

    def __str__(self):
        return f'{self.project.title} - {self.name}'
