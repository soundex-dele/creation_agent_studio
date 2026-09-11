from django.contrib import admin

from .models import Workflow, WorkflowStep


class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'owner', 'is_public', 'updated_at']
    search_fields = ['name', 'description']
    inlines = [WorkflowStepInline]
