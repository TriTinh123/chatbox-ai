from django.shortcuts import render
from django.http import JsonResponse


def chatbot_index(request):
    """Serve the main chatbot UI."""
    return render(request, 'chatbot/index.html')


def health_check(request):
    return JsonResponse({'status': 'ok'})


def custom_404(request, exception=None):
    return render(request, '404.html', status=404)


def custom_500(request):
    return render(request, '500.html', status=500)

