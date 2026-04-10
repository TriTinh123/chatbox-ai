"""
Production settings — deployed server only.
Never set DEBUG=True or commit real secrets here.
"""

from .base import *  # noqa
from decouple import config

DEBUG = False

# ── Database — PostgreSQL ─────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME':     config('POSTGRES_DB',       default='revenueai'),
        'USER':     config('POSTGRES_USER',     default='revenueai'),
        'PASSWORD': config('POSTGRES_PASSWORD'),
        'HOST':     config('POSTGRES_HOST',     default='db'),
        'PORT':     config('POSTGRES_PORT',     default='5432'),
        'CONN_MAX_AGE': 60,
        'OPTIONS': {
            'connect_timeout': 10,
            'sslmode': config('POSTGRES_SSLMODE', default='prefer'),
        },
    }
}

# ── Cache — Redis (fallback to local memory if not configured) ────────────
REDIS_URL = config('REDIS_URL', default='')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'TIMEOUT': 300,
            'OPTIONS': {'max_entries': 10000},
        }
    }
    # Use cache-backed sessions
    SESSION_ENGINE      = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'

# ── Security — HTTPS hardening ────────────────────────────────────────────
SECURE_SSL_REDIRECT                  = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SECURE_PROXY_SSL_HEADER              = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE                = True
CSRF_COOKIE_SECURE                   = True
CSRF_COOKIE_HTTPONLY                 = True
SESSION_COOKIE_HTTPONLY              = True
SECURE_HSTS_SECONDS                  = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS       = True
SECURE_HSTS_PRELOAD                  = True
SECURE_CONTENT_TYPE_NOSNIFF          = True
X_FRAME_OPTIONS                      = 'DENY'
SECURE_REFERRER_POLICY               = 'strict-origin-when-cross-origin'

# ── CORS — explicit allowlist in production ───────────────────────────────
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='',
    cast=lambda v: [s.strip() for s in v.split(',') if s.strip()]
)
CORS_ALLOW_CREDENTIALS = True

# ── Static files (served by whitenoise) ───────────────────────────────────
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Email (configure SMTP in .env) ────────────────────────────────────────
EMAIL_BACKEND   = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST      = config('EMAIL_HOST',      default='smtp.gmail.com')
EMAIL_PORT      = config('EMAIL_PORT',      default=587, cast=int)
EMAIL_USE_TLS   = config('EMAIL_USE_TLS',   default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')

# ── Logging — structured, production-grade ───────────────────────────────
LOGGING['root']['level'] = 'WARNING'           # noqa
LOGGING['loggers']['django']['level'] = 'WARNING'  # noqa
LOGGING['handlers']['file'] = {               # noqa
    'class':     'logging.handlers.RotatingFileHandler',
    'filename':  BASE_DIR / 'logs' / 'production.log',  # noqa
    'maxBytes':  10 * 1024 * 1024,  # 10 MB
    'backupCount': 5,
    'formatter': 'verbose',
}
LOGGING['loggers']['revenueai'] = {           # noqa
    'handlers':  ['console', 'file'],
    'level':     'INFO',
    'propagate': False,
}
