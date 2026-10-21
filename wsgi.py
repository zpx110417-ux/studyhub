"""生产部署入口：gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app"""
from app import create_app

app = create_app()
