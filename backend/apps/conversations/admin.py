"""
Admin configuration for conversations app.
"""
from django.contrib import admin
from apps.conversations.models import Conversation, Message, MessageAttachment


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    """
    Admin interface for Conversation model.
    """
    list_display = ['id', 'user', 'agent', 'title', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['title', 'user__username']
    ordering = ['-updated_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """
    Admin interface for Message model.
    """
    list_display = ['id', 'conversation', 'role', 'content_preview', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['content']
    ordering = ['created_at']
    readonly_fields = ['created_at']

    def content_preview(self, obj):
        """
        Return a preview of the message content.
        """
        return obj.content[:100]
    content_preview.short_description = 'Content'


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'conversation', 'message', 'original_name', 'content_type',
        'byte_size', 'created_at',
    ]
    list_filter = ['content_type', 'created_at']
    search_fields = ['original_name', 'checksum_sha256']
    readonly_fields = ['created_at']
