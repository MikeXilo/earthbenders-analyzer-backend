"""
Celery configuration for async terrain processing
Uses PostgreSQL as both broker and result backend to avoid Redis costs
"""
import os
from celery import Celery

# Create Celery app
app = Celery('earthbenders')

# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

# Configure Celery to use PostgreSQL as broker and result backend
app.conf.update(
    # Use SQLAlchemy with PostgreSQL as broker
    broker_url=f"sqla+postgresql://{DATABASE_URL.split('://')[1]}",
    result_backend=f"db+postgresql://{DATABASE_URL.split('://')[1]}",
    
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task routing
    task_routes={
        'services.tasks.process_terrain_async': {'queue': 'terrain_processing'},
        'services.tasks.process_lidar_async': {'queue': 'lidar_processing'},
    },
    
    # Worker configuration
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_max_tasks_per_child=50,
    
    # Task time limits
    task_time_limit=1800,  # 30 minutes max per task
    task_soft_time_limit=1500,  # 25 minutes soft limit
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_persistent=True,
)

# Import tasks to register them
from services.tasks import process_terrain_async

if __name__ == '__main__':
    app.start()
