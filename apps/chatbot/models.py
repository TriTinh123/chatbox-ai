from django.db import models
from django.contrib.auth.models import User
import json


class SalesData(models.Model):
    """Store imported sales CSV data."""
    date = models.DateField()
    source_file = models.CharField(max_length=255, blank=True, default='')
    product = models.CharField(max_length=100)
    channel = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    quantity = models.IntegerField()
    unit_price = models.BigIntegerField()  # Vietnamese currency
    revenue = models.BigIntegerField()
    
    class Meta:
        indexes = [
            models.Index(fields=['date', 'product']),
            models.Index(fields=['date', 'channel']),
        ]
    
    def __str__(self):
        return f"{self.date} - {self.product}: {self.quantity} x {self.unit_price}"


class ChatSession(models.Model):
    """Store chat conversation sessions."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions', null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    pinned = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.title or 'Untitled'}"


class Message(models.Model):
    """Store individual messages in a chat session."""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]
    
    chat_session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    text = models.TextField()  # Plain text content
    html = models.TextField(blank=True)  # Rendered HTML content
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.chat_session.id} - {self.role}: {self.text[:50]}"


class FileAttachment(models.Model):
    """Store uploaded CSV files."""
    chat_session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='uploads/', blank=True, null=True)
    filename = models.CharField(max_length=255)
    rows_count = models.IntegerField(null=True, blank=True)
    cols_count = models.IntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.filename} ({self.rows_count}x{self.cols_count})"
