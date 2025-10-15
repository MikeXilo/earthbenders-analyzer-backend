# Railway Procfile for dual service deployment
# Web service: Handles HTTP requests
# Worker service: Processes async tasks

web: python3 create_tables.py && python3 migrate_analyses_table.py && gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 4 --worker-class sync --access-logfile - --error-logfile - server:app

worker: celery -A celery_config worker -l info --concurrency=2 --max-tasks-per-child=50