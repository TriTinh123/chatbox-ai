"""
Development settings - local development only.
"""

from .base import *  # noqa
from decouple import config

DEBUG = True

# Development database (SQLite)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# CORS - allow all origins in dev
CORS_ALLOW_ALL_ORIGINS = True

# Debug Toolbar (optional, install django-debug-toolbar)
# INSTALLED_APPS += ['debug_toolbar']
# MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
# INTERNAL_IPS = ['127.0.0.1']

# Email backend - print to console
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging override for dev
LOGGING['root']['level'] = 'DEBUG'  # noqa
