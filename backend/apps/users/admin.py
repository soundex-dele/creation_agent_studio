"""
Admin configuration for users app.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

User = get_user_model()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Admin interface for User model.
    """
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Agent Studio', {'fields': ('role', 'avatar', 'bio')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Agent Studio', {'fields': ('email', 'role')}),
    )
    list_display = [
        'username', 'email', 'role', 'first_name', 'last_name',
        'is_staff', 'is_active',
    ]
    list_filter = ['role', 'is_staff', 'is_active', 'is_superuser']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering = ['username']
