from django.contrib import admin
from .models import SalesData, ChatSession, Message, FileAttachment


@admin.register(SalesData)
class SalesDataAdmin(admin.ModelAdmin):
    list_display = ['date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue']
    list_filter = ['date', 'product', 'channel', 'region']
    search_fields = ['product', 'channel', 'region']
    readonly_fields = ['revenue']
    date_hierarchy = 'date'


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'title', 'created_at', 'pinned']
    list_filter = ['created_at', 'pinned']
    search_fields = ['user__username', 'title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['chat_session', 'role', 'text_preview', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['text', 'chat_session__title']
    readonly_fields = ['created_at']
    
    def text_preview(self, obj):
        return obj.text[:50] + '...' if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Text'


@admin.register(FileAttachment)
class FileAttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'chat_session', 'rows_count', 'cols_count', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['filename']
    readonly_fields = ['uploaded_at']
