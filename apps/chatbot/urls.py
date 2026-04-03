from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChatSessionViewSet, PublicChatViewSet, health_check_view

router = DefaultRouter()
router.register(r'chats', ChatSessionViewSet, basename='chat')
router.register(r'public', PublicChatViewSet, basename='public-chat')

urlpatterns = [
    path('', include(router.urls)),
    path('health/', health_check_view, name='health-check'),
]
