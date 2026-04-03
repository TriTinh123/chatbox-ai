from rest_framework import serializers
from .models import SalesData, ChatSession, Message, FileAttachment


class SalesDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesData
        fields = ['id', 'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue']


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'role', 'text', 'html', 'created_at']


class FileAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileAttachment
        fields = ['id', 'filename', 'rows_count', 'cols_count', 'uploaded_at']


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    attachments = FileAttachmentSerializer(many=True, read_only=True)
    
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'created_at', 'updated_at', 'pinned', 'messages', 'attachments']


class ChatSessionDetailSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'created_at', 'updated_at', 'pinned', 'messages']


class ChatSessionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'created_at', 'updated_at', 'pinned']


class MessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['role', 'text', 'html']

