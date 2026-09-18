"""
Models for users app.
"""
import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager


class UserManager(DjangoUserManager):
    """Keep Django superusers aligned with the application's admin role."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model for Agent Studio.

    Extends Django's AbstractUser to add custom fields and functionality.
    """

    class Role(models.TextChoices):
        ADMIN = 'admin', '管理员'
        PROFESSIONAL = 'professional', '专业用户'
        MEMBER = 'member', '成员'
        VIEWER = 'viewer', '查看者'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER
    )
    objects = UserManager()
    avatar = models.URLField(blank=True, help_text='用户头像 URL')
    bio = models.TextField(blank=True, help_text='用户简介')
    api_key = models.CharField(
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text='API 密钥'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    def generate_api_key(self):
        """生成兼容旧接口的 API 密钥，数据库只保存不可逆哈希。"""
        raw_key = f'ast_{secrets.token_urlsafe(32)}'
        self.api_key = make_password(raw_key)
        self.save(update_fields=['api_key', 'updated_at'])
        return raw_key

    def check_api_key(self, raw_key: str) -> bool:
        return bool(self.api_key and check_password(raw_key, self.api_key))


class UserAPIKey(models.Model):
    """可审计、可撤销、带作用域的用户/服务 API Key。"""

    id = models.UUIDField(primary_key=True, default=__import__('uuid').uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_keys'
    )
    name = models.CharField(max_length=100, default='default')
    prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_api_keys'
        ordering = ['-created_at']

    @staticmethod
    def digest(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, *, user, name='default', scopes=None, expires_at=None):
        raw_key = f'ast_{secrets.token_urlsafe(32)}'
        obj = cls.objects.create(
            user=user,
            name=name,
            prefix=raw_key[:12],
            key_hash=cls.digest(raw_key),
            scopes=scopes or [],
            expires_at=expires_at,
        )
        return obj, raw_key

    def matches(self, raw_key: str) -> bool:
        return secrets.compare_digest(self.key_hash, self.digest(raw_key))
