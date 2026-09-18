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
        ('Agent Studio', {'fields': (
            'role', 'avatar', 'bio',
            'can_view_agents', 'can_create_agents', 'can_update_agents',
            'can_delete_agents', 'can_toggle_agents',
            'can_view_applications', 'can_toggle_applications',
        )}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Agent Studio', {'fields': (
            'email', 'role',
            'can_view_agents', 'can_create_agents', 'can_update_agents',
            'can_delete_agents', 'can_toggle_agents',
            'can_view_applications', 'can_toggle_applications',
        )}),
    )
    list_display = [
        'username', 'email', 'role', 'first_name', 'last_name',
        'is_staff', 'is_active',
    ]
    list_filter = [
        'role', 'can_view_agents', 'can_create_agents', 'can_update_agents',
        'can_delete_agents', 'can_toggle_agents',
        'can_view_applications', 'can_toggle_applications',
        'is_staff', 'is_active', 'is_superuser',
    ]
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering = ['username']
