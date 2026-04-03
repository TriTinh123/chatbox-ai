# Chatbox AI - Django Project

Dự án Django với cấu trúc chuẩn production. Tích hợp chatbot phân tích doanh thu từ dự án cũ `sales_boxchat`.

## Features

- ✅ **Cấu trúc production-ready**: Settings tách base/dev/prod
- ✅ **Chatbot API**: RESTful API cho AI chatbot phân tích doanh thu
- ✅ **Data Analysis**: Phân tích doanh thu bằng pandas
- ✅ **Machine Learning**: Dự báo doanh thu bằng scikit-learn
- ✅ **Gemini Integration**: Fallback AI API cho câu hỏi mở
- ✅ **Database**: Multi-model (User, Chat, Message, SalesData)
- ✅ **Security**: HSTS, SSL, XFrame, CSRF protections
- ✅ **Docker Support**: Dockerfile + docker-compose.yml

## Cấu trúc thư mục

```
chatbox-ai/
├── apps/
│   ├── __init__.py
│   ├── core/                    # Core app
│   └── chatbot/                 # Chatbot app (NEW)
│       ├── models.py            # SalesData, ChatSession, Message
│       ├── views.py             # REST API ViewSets
│       ├── serializers.py       # DRF Serializers
│       ├── admin.py             # Django Admin
│       ├── urls.py              # URL routes
│       ├── services/            # Business logic
│       │   ├── analysis.py
│       │   ├── forecasting.py
│       │   ├── insights.py
│       │   └── ...
│       └── management/commands/
│           └── load_sales_data.py
├── config/
│   ├── settings/
│   │   ├── base.py              # Cài đặt chung
│   │   ├── development.py       # Dev (SQLite)
│   │   └── production.py        # Production (PostgreSQL)
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── requirements/
│   ├── base.txt
│   ├── development.txt
│   ├── production.txt
│   └── all.txt
├── static/
│   ├── css/
│   ├── js/
│   └── images/
├── templates/
│   ├── base.html
│   ├── core/
│   └── chatbot/
├── media/
├── logs/
├── docker-compose.yml
├── Dockerfile
├── Procfile
└── manage.py
```

## Cài đặt & Chạy

### 1. Activate virtual environment

```bash
# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 2. Cấu hình biến môi trường

```bash
cp .env.example .env
# Chỉnh sửa .env với thông tin thực tế
```

### 3. Cài dependencies

```bash
# Development
pip install -r requirements/development.txt

# Production
pip install -r requirements/production.txt
```

### 4. Chạy migrations

```bash
python manage.py migrate
```

### 5. Tạo superuser

```bash
python manage.py createsuperuser
```

### 6. Chạy server

```bash
# Development
python manage.py runserver

# Production (Gunicorn)
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

## Docker

```bash
docker-compose up --build
```

## Environment Variables

| Tên | Mô tả | Bắt buộc |
|-----|-------|----------|
| `SECRET_KEY` | Django secret key | Có |
| `ALLOWED_HOSTS` | Danh sách host cho phép | Có |
| `DB_NAME` | Tên database | Production |
| `DB_USER` | User database | Production |
| `DB_PASSWORD` | Mật khẩu database | Production |
| `REDIS_URL` | URL Redis cache | Production |

## Endpoints

- `/admin/` — Django Admin
- `/health/` — Health check
- `/api/` — API routes
