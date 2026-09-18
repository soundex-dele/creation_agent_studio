"""
Serializers for users app.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """用户序列化器"""

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'avatar', 'bio', 'created_at',
        ]
        read_only_fields = [
            'id', 'role', 'created_at',
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    """用户详情序列化器"""

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'avatar', 'bio',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'role', 'created_at', 'updated_at',
        ]


class RegisterSerializer(serializers.ModelSerializer):
    """注册序列化器"""
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': '两次输入的密码不一致'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class AdminUserSerializer(serializers.ModelSerializer):
    """Account data accepted only from an authenticated platform administrator."""

    password = serializers.CharField(
        write_only=True,
        required=False,
        validators=[validate_password],
        style={'input_type': 'password'},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=False,
        style={'input_type': 'password'},
    )

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'is_active',
            'password', 'password_confirm', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': '请输入初始密码。'})
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError({
                'password_confirm': '两次输入的密码不一致',
            })
        actor = getattr(self.context.get('request'), 'user', None)
        if self.instance is not None and actor is not None:
            if self.instance.is_superuser and not actor.is_superuser:
                raise serializers.ValidationError({
                    'detail': '只有超级管理员可以修改超级管理员账号。',
                })
            role = attrs.get('role', self.instance.role)
            is_active = attrs.get('is_active', self.instance.is_active)
            sensitive_change = role != self.instance.role or is_active != self.instance.is_active
            if actor.pk == self.instance.pk and sensitive_change:
                raise serializers.ValidationError({
                    'detail': '不能修改自己的平台角色或登录状态。',
                })
            removes_admin = (
                self.instance.is_active
                and self.instance.role == User.Role.ADMIN
                and (not is_active or role != User.Role.ADMIN)
            )
            if removes_admin and not User.objects.filter(
                role=User.Role.ADMIN, is_active=True,
            ).exclude(pk=self.instance.pk).exists():
                raise serializers.ValidationError({
                    'detail': '系统必须至少保留一个有效的平台管理员。',
                })
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('password_confirm', None)
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=['password', 'updated_at'])
        return instance


class LoginSerializer(serializers.Serializer):
    """登录序列化器"""
    username = serializers.CharField(required=True)
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )


class ChangePasswordSerializer(serializers.Serializer):
    """修改密码序列化器"""
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': '两次输入的密码不一致'})
        return attrs
