from django.shortcuts import render
from django.http import JsonResponse


def chatbot_index(request):
    """Serve the main chatbot UI."""
    return render(request, 'chatbot/index.html')


def health_check(request):
    return JsonResponse({'status': 'ok'})

