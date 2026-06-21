"""
Production-Grade Celery Task Queue System
Implements async job processing, retries, and distributed task execution
"""

from celery import Celery, Task
from celery.schedules import crontab
from celery.signals import task_prerun, task_postrun, task_failure
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import logging
from config.settings import settings

# Initialize Celery
_broker = getattr(settings, 'CELERY_BROKER_URL',
            getattr(settings, 'redis_url', 'redis://localhost:6379/0'))
_backend = getattr(settings, 'CELERY_RESULT_BACKEND', _broker)

celery_app = Celery(
    "ai_job_agent",
    broker=_broker,
    backend=_backend,
    include=[
        "workers.job_search",
        "workers.resume_generation",
        "workers.application_submission",
        "workers.monitoring"
    ]
)

# Celery Configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Performance settings
    task_acks_late=True,  # Ack tasks after completion
    worker_prefetch_multiplier=1,  # One task at a time
    task_reject_on_worker_lost=True,  # Retry if worker dies
    
    # Retry settings
    task_annotations={
        "*": {
            "max_retries": 3,
            "default_retry_delay": 60,  # 1 minute
        }
    },
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
    },
    
    # Worker settings
    worker_max_tasks_per_child=1000,  # Restart after 1000 tasks
    worker_disable_rate_limits=False,
    
    # Monitoring
    task_send_sent_event=True,
    worker_send_task_events=True,
    
    # Task routing
    task_routes={
        "workers.job_search.*": {"queue": "job_search"},
        "workers.resume_generation.*": {"queue": "resume"},
        "workers.application_submission.*": {"queue": "applications"},
        "workers.monitoring.*": {"queue": "monitoring"},
    },
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        "daily-job-search": {
            "task": "workers.job_search.run_daily_search",
            "schedule": crontab(hour=0, minute=0),  # Midnight daily
        },
        "cleanup-old-jobs": {
            "task": "workers.monitoring.cleanup_old_data",
            "schedule": crontab(hour=2, minute=0),  # 2 AM daily
        },
        "generate-metrics": {
            "task": "workers.monitoring.generate_metrics",
            "schedule": crontab(minute="*/15"),  # Every 15 minutes
        },
    },
)


class BaseTask(Task):
    """Base task with retry logic and error handling"""
    
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True  # Exponential backoff
    retry_backoff_max = 600  # Max 10 minutes
    retry_jitter = True  # Add randomness to backoff
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handler for task failure"""
        logging.error(f"Task {self.name} failed: {exc}")
        # Send alert to monitoring system
        from infrastructure.monitoring import alert_manager
        alert_manager.send_alert(
            severity="error",
            message=f"Task {self.name} failed: {exc}",
            task_id=task_id
        )
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Handler for task retry"""
        logging.warning(f"Task {self.name} retrying: {exc}")
    
    def on_success(self, retval, task_id, args, kwargs):
        """Handler for task success"""
        logging.info(f"Task {self.name} completed successfully")


# Task monitoring signals
@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
    """Called before task execution"""
    if task is not None:
        logging.info(f"Starting task {task.name} [{task_id}]")


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, **kwargs):
    """Called after task execution"""
    if task is not None:
        logging.info(f"Finished task {task.name} [{task_id}]")


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
    """Called on task failure"""
    logging.error(f"Task failed [{task_id}]: {exception}")


# Priority levels for tasks
class TaskPriority:
    CRITICAL = 0
    HIGH = 3
    NORMAL = 5
    LOW = 7
    BACKGROUND = 9


# Task result tracking
class TaskResult:
    """Track task results and status"""
    
    @staticmethod
    def get_status(task_id: str) -> dict:
        """Get task status"""
        result = celery_app.AsyncResult(task_id)
        return {
            "task_id": task_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback,
        }
    
    @staticmethod
    def wait_for_task(task_id: str, timeout: int = 300) -> Any:
        """Wait for task to complete"""
        result = celery_app.AsyncResult(task_id)
        return result.get(timeout=timeout)
    
    @staticmethod
    def cancel_task(task_id: str) -> bool:
        """Cancel running task"""
        celery_app.control.revoke(task_id, terminate=True)
        return True


# Task utilities
class TaskUtils:
    """Utility functions for task management"""
    
    @staticmethod
    def chain_tasks(tasks: list) -> Any:
        """Chain multiple tasks to run sequentially"""
        from celery import chain
        return chain(*tasks)()
    
    @staticmethod
    def group_tasks(tasks: list) -> Any:
        """Run multiple tasks in parallel"""
        from celery import group
        return group(*tasks)()
    
    @staticmethod
    def chord_tasks(header: list, callback: Task) -> Any:
        """Run tasks in parallel then callback"""
        from celery import chord
        return chord(header)(callback)


# Queue management
class QueueManager:
    """Manage task queues"""
    
    @staticmethod
    def get_queue_length(queue_name: str) -> int:
        """Get number of tasks in queue"""
        from celery.app.control import Inspect
        inspect = Inspect(app=celery_app)
        reserved = inspect.reserved()
        
        if not reserved:
            return 0
        
        total = 0
        for worker, tasks in reserved.items():
            total += len([t for t in tasks if t.get("delivery_info", {}).get("routing_key") == queue_name])
        
        return total
    
    @staticmethod
    def purge_queue(queue_name: str) -> int:
        """Remove all tasks from queue"""
        celery_app.control.purge()
        return 0
    
    @staticmethod
    def get_active_tasks() -> dict:
        """Get currently running tasks"""
        from celery.app.control import Inspect
        inspect = Inspect(app=celery_app)
        return inspect.active() or {}
    
    @staticmethod
    def get_worker_stats() -> dict:
        """Get worker statistics"""
        from celery.app.control import Inspect
        inspect = Inspect(app=celery_app)
        return {
            "stats": inspect.stats(),
            "active_queues": inspect.active_queues(),
            "registered_tasks": inspect.registered(),
        }


# Rate limiting for tasks
def rate_limit_task(task_name: str, limit: int, period: int):
    """
    Decorator to rate limit task execution
    
    Args:
        task_name: Name of the task
        limit: Maximum number of executions
        period: Time period in seconds
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            from infrastructure.cache import RateLimitCache
            
            allowed, remaining = RateLimitCache.check_rate_limit(
                user_id=task_name,
                limit=limit,
                window=period
            )
            
            if not allowed:
                raise Exception(f"Rate limit exceeded for {task_name}")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Dead Letter Queue for failed tasks
class DeadLetterQueue:
    """Handle permanently failed tasks"""
    
    @staticmethod
    def add_failed_task(task_id: str, exception: str, args: tuple, kwargs: dict):
        """Add failed task to DLQ"""
        from infrastructure.cache import cache
        
        dlq_key = f"dlq:{task_id}"
        dlq_data = {
            "task_id": task_id,
            "exception": str(exception),
            "args": args,
            "kwargs": kwargs,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        
        cache.set(dlq_key, dlq_data, ttl=86400 * 7)  # Keep for 7 days
    
    @staticmethod
    def get_failed_tasks(limit: int = 100) -> list:
        """Get failed tasks from DLQ"""
        from infrastructure.cache import cache
        
        keys = cache.redis.keys("dlq:*")
        failed_tasks = []
        
        for key in keys[:limit]:
            task_data = cache.get(key.decode())
            if task_data:
                failed_tasks.append(task_data)
        
        return failed_tasks
    
    @staticmethod
    def retry_failed_task(task_id: str):
        """Retry a failed task from DLQ"""
        from infrastructure.cache import cache
        
        dlq_key = f"dlq:{task_id}"
        task_data = cache.get(dlq_key)
        
        if not task_data:
            raise Exception(f"Task {task_id} not found in DLQ")
        
        # Re-queue the task
        # Implementation depends on task type
        cache.delete(dlq_key)
