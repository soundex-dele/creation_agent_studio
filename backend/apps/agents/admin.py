"""
Admin configuration for agents app.
"""
from django.contrib import admin
from apps.agents.models import AgentCategory, Agent, AgentSkillBinding


@admin.register(AgentCategory)
class AgentCategoryAdmin(admin.ModelAdmin):
    """Admin interface for AgentCategory model."""
    list_display = ['name', 'slug', 'order']
    list_filter = ['order']
    search_fields = ['name', 'description']
    ordering = ['order']


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    """Admin interface for Agent model."""
    list_display = ['name', 'category', 'slug', 'is_public', 'created_by', 'created_at', 'updated_at']
    list_filter = ['category', 'is_public', 'created_at']
    search_fields = ['name', 'description', 'slug']
    ordering = ['category__order', 'name']
    readonly_fields = ['created_at', 'updated_at']


admin.site.register(AgentSkillBinding)
