FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories
RUN mkdir -p logs media

# Collect static files
RUN DJANGO_SETTINGS_MODULE=config.settings.railway python manage.py collectstatic --noinput

# Run migrations then start server
CMD python manage.py migrate && gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 2 config.wsgi:application
