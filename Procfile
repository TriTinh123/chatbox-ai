web: gunicorn --bind 0.0.0.0:$PORT --timeout 120 config.wsgi:application
release: python manage.py migrate
