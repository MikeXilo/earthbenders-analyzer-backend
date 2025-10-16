# Railway Procfile for single service deployment
# Web service: Handles HTTP requests and background processing

web: python3 create_tables.py && python3 migrate_analyses_table.py && python3 migrate_polygon_geometry.py && gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 4 --worker-class sync --access-logfile - --error-logfile - server:app