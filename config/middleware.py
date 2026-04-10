"""
Custom middleware for Revenue AI.

Middleware stack (registered in settings):
  1. RequestIDMiddleware      — attach unique X-Request-ID to every request
  2. RequestLoggingMiddleware — structured access log with timing + status
  3. SecurityHeadersMiddleware— extra security headers beyond Django defaults
"""

import uuid
import time
import logging

logger = logging.getLogger('revenueai.requests')


class RequestIDMiddleware:
    """
    Attach a short unique ID to every request.
    Visible in response header X-Request-ID for support tracing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:10]
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        return response


class RequestLoggingMiddleware:
    """
    Log every request:  METHOD path  status  Xms  [ip] [req-id]
    Skips static/media to reduce noise.
    """

    SKIP_PREFIXES = ('/static/', '/media/', '/favicon')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in self.SKIP_PREFIXES):
            return self.get_response(request)

        t0 = time.perf_counter()
        response = self.get_response(request)
        ms = round((time.perf_counter() - t0) * 1000)

        ip = (
            request.META.get('HTTP_X_FORWARDED_FOR', '')
            .split(',')[0].strip()
            or request.META.get('REMOTE_ADDR', '-')
        )
        rid = getattr(request, 'request_id', '-')

        logger.info(
            '%s %s → %d  %dms  [%s] [%s]',
            request.method, request.path,
            response.status_code, ms,
            ip, rid,
        )
        return response


class SecurityHeadersMiddleware:
    """
    Security headers not automatically set by Django's SecurityMiddleware.
    Works independently of HTTPS so it applies in dev too.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Prevent MIME-type sniffing
        response.setdefault('X-Content-Type-Options', 'nosniff')

        # Referrer controls
        response.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')

        # Permissions: only mic from same origin (needed for voice input)
        response.setdefault(
            'Permissions-Policy',
            'geolocation=(), camera=(), microphone=(self)'
        )

        # Content Security Policy
        # - fonts.googleapis.com / fonts.gstatic.com: Inter / JetBrains Mono
        # - cdn.jsdelivr.net: Chart.js
        # - 'unsafe-inline' for styles needed by inline SVG / Chart.js canvas
        response.setdefault(
            'Content-Security-Policy',
            (
                "default-src 'self'; "
                "script-src 'self' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "connect-src 'self' https://cdn.jsdelivr.net; "
                "frame-ancestors 'none';"
            )
        )

        # Remove server fingerprint
        response['Server'] = 'Revenue AI'

        return response
