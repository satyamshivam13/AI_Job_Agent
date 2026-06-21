"""
Production-Grade Monitoring & Observability System
Implements Prometheus metrics, OpenTelemetry tracing, and structured logging
"""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest
try:
    from opentelemetry import trace, metrics  # type: ignore[import-untyped]
    from opentelemetry.exporter.prometheus import PrometheusMetricReader  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-untyped]
    from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[import-untyped]
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import-untyped]
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # type: ignore[import-untyped]
    from opentelemetry.instrumentation.redis import RedisInstrumentor  # type: ignore[import-untyped]
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    class _Stub:
        def __getattr__(self, n): return self
        def __call__(self, *a, **k): return self
    trace = metrics = TracerProvider = BatchSpanProcessor = None
    PrometheusMetricReader = MeterProvider = None
    FastAPIInstrumentor = SQLAlchemyInstrumentor = RedisInstrumentor = None
import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import structlog
from config.settings import settings

# ==================== PROMETHEUS METRICS ====================

# Application Info
app_info = Info("ai_job_agent", "AI Job Agent application information")
app_info.info({
    "version": "2.0.0",
    "environment": getattr(settings, 'ENVIRONMENT', getattr(settings, 'environment', 'production'))
})

# Request Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"]
)

# Job Search Metrics
jobs_scraped_total = Counter(
    "jobs_scraped_total",
    "Total jobs scraped",
    ["platform", "status"]
)

job_search_duration = Histogram(
    "job_search_duration_seconds",
    "Job search duration",
    ["platform"]
)

# Application Metrics
applications_submitted_total = Counter(
    "applications_submitted_total",
    "Total applications submitted",
    ["platform", "status"]
)

application_submission_duration = Histogram(
    "application_submission_duration_seconds",
    "Application submission duration",
    ["platform"]
)

# Resume Generation Metrics
resumes_generated_total = Counter(
    "resumes_generated_total",
    "Total resumes generated",
    ["variant", "status"]
)

resume_generation_duration = Histogram(
    "resume_generation_duration_seconds",
    "Resume generation duration",
    ["variant"]
)

resume_ats_score = Histogram(
    "resume_ats_score",
    "Resume ATS compatibility score",
    ["variant"],
    buckets=[0, 50, 60, 70, 75, 80, 85, 90, 95, 100]
)

# LLM Metrics
llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API requests",
    ["model", "provider", "cached"]
)

llm_tokens_used = Counter(
    "llm_tokens_used_total",
    "Total LLM tokens used",
    ["model", "provider", "type"]  # type: prompt or completion
)

llm_cost_usd = Counter(
    "llm_cost_usd_total",
    "Total LLM cost in USD",
    ["model", "provider"]
)

llm_request_duration = Histogram(
    "llm_request_duration_seconds",
    "LLM request duration",
    ["model", "provider"]
)

llm_cache_hit_rate = Gauge(
    "llm_cache_hit_rate",
    "LLM cache hit rate percentage",
    ["model"]
)

# Database Metrics
db_queries_total = Counter(
    "db_queries_total",
    "Total database queries",
    ["operation", "table"]
)

db_query_duration = Histogram(
    "db_query_duration_seconds",
    "Database query duration",
    ["operation", "table"]
)

db_connections_active = Gauge(
    "db_connections_active",
    "Active database connections"
)

# Cache Metrics
cache_operations_total = Counter(
    "cache_operations_total",
    "Total cache operations",
    ["operation", "status"]  # operation: get/set/delete, status: hit/miss/error
)

cache_hit_rate = Gauge(
    "cache_hit_rate",
    "Cache hit rate percentage",
    ["cache_type"]
)

# Task Queue Metrics
celery_tasks_total = Counter(
    "celery_tasks_total",
    "Total Celery tasks",
    ["task_name", "status"]  # status: success/failure/retry
)

celery_task_duration = Histogram(
    "celery_task_duration_seconds",
    "Celery task duration",
    ["task_name"]
)

celery_queue_length = Gauge(
    "celery_queue_length",
    "Number of tasks in queue",
    ["queue_name"]
)

# System Metrics
system_errors_total = Counter(
    "system_errors_total",
    "Total system errors",
    ["error_type", "component"]
)

active_users = Gauge(
    "active_users",
    "Number of active users"
)

# Interview Metrics
interviews_received_total = Counter(
    "interviews_received_total",
    "Total interview invitations received",
    ["platform", "stage"]  # stage: phone_screen, technical, final
)

interview_rate = Gauge(
    "interview_rate_percentage",
    "Interview invitation rate",
    ["platform"]
)


# ==================== OPENTELEMETRY TRACING ====================

if _OTEL_AVAILABLE and TracerProvider:
    tracer_provider = TracerProvider()
    trace.set_tracer_provider(tracer_provider)
    tracer = trace.get_tracer(__name__)
    meter_provider = MeterProvider() if MeterProvider else None
    if meter_provider and metrics:
        metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter(__name__) if metrics else None
else:
    tracer_provider = None
    tracer = None
    meter_provider = None
    meter = None


class TracingManager:
    """Manage distributed tracing"""
    
    @staticmethod
    def create_span(name: str, attributes: Optional[Dict[str, Any]] = None):
        """Create a new trace span"""
        if tracer is None:
            return None
        with tracer.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            return span

    @staticmethod
    def add_event(span, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Add event to current span"""
        span.add_event(name, attributes=attributes or {})

    @staticmethod
    def record_exception(span, exception: Exception):
        """Record exception in span"""
        span.record_exception(exception)
        if trace is not None:
            span.set_status(trace.Status(trace.StatusCode.ERROR))


# ==================== STRUCTURED LOGGING ====================

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Get structured logger
logger = structlog.get_logger()


class StructuredLogger:
    """Structured logging for better observability"""
    
    @staticmethod
    def log_request(method: str, endpoint: str, status: int, duration: float, user_id: Optional[str] = None):
        """Log HTTP request"""
        logger.info(
            "http_request",
            method=method,
            endpoint=endpoint,
            status=status,
            duration_seconds=duration,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Update Prometheus metrics
        http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=status
        ).inc()
        
        http_request_duration.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    @staticmethod
    def log_job_search(platform: str, query: str, jobs_found: int, duration: float, status: str):
        """Log job search operation"""
        logger.info(
            "job_search",
            platform=platform,
            query=query,
            jobs_found=jobs_found,
            duration_seconds=duration,
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Update Prometheus metrics
        jobs_scraped_total.labels(
            platform=platform,
            status=status
        ).inc(jobs_found)
        
        job_search_duration.labels(platform=platform).observe(duration)
    
    @staticmethod
    def log_llm_request(
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        duration: float,
        cached: bool
    ):
        """Log LLM API request"""
        logger.info(
            "llm_request",
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost_usd,
            duration_seconds=duration,
            cached=cached,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Update Prometheus metrics
        llm_requests_total.labels(
            model=model,
            provider=provider,
            cached="true" if cached else "false"
        ).inc()
        
        llm_tokens_used.labels(
            model=model,
            provider=provider,
            type="prompt"
        ).inc(prompt_tokens)
        
        llm_tokens_used.labels(
            model=model,
            provider=provider,
            type="completion"
        ).inc(completion_tokens)
        
        llm_cost_usd.labels(
            model=model,
            provider=provider
        ).inc(cost_usd)
        
        llm_request_duration.labels(
            model=model,
            provider=provider
        ).observe(duration)
    
    @staticmethod
    def log_error(
        error_type: str,
        component: str,
        message: str,
        exception: Optional[Exception] = None,
        user_id: Optional[str] = None
    ):
        """Log error"""
        logger.error(
            "system_error",
            error_type=error_type,
            component=component,
            message=message,
            exception=str(exception) if exception else None,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Update Prometheus metrics
        system_errors_total.labels(
            error_type=error_type,
            component=component
        ).inc()
    
    @staticmethod
    def log_application_submission(
        platform: str,
        job_id: str,
        status: str,
        duration: float,
        user_id: str
    ):
        """Log job application submission"""
        logger.info(
            "application_submission",
            platform=platform,
            job_id=job_id,
            status=status,
            duration_seconds=duration,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Update Prometheus metrics
        applications_submitted_total.labels(
            platform=platform,
            status=status
        ).inc()
        
        application_submission_duration.labels(platform=platform).observe(duration)


# ==================== ALERT MANAGER ====================

class AlertManager:
    """Manage alerts and notifications"""
    
    SEVERITY_CRITICAL = "critical"
    SEVERITY_ERROR = "error"
    SEVERITY_WARNING = "warning"
    SEVERITY_INFO = "info"
    
    @staticmethod
    def send_alert(severity: str, message: str, component: Optional[str] = None, **kwargs):
        """Send alert to monitoring system"""
        alert_data = {
            "severity": severity,
            "message": message,
            "component": component,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs
        }
        
        logger.warning("alert", **alert_data)
        
        # In production, send to PagerDuty, Slack, etc.
        if severity == AlertManager.SEVERITY_CRITICAL:
            # Send to PagerDuty
            pass
        elif severity == AlertManager.SEVERITY_ERROR:
            # Send to Slack
            pass
    
    @staticmethod
    def check_system_health() -> dict:
        """Check system health and send alerts if needed"""
        health = {
            "status": "healthy",
            "checks": {}
        }
        
        # Check database
        try:
            from models.database import _get_engine
            with _get_engine().connect() as conn:
                conn.execute("SELECT 1")
            health["checks"]["database"] = "healthy"
        except Exception as e:
            health["checks"]["database"] = "unhealthy"
            health["status"] = "degraded"
            AlertManager.send_alert(
                severity=AlertManager.SEVERITY_ERROR,
                message=f"Database health check failed: {e}",
                component="database"
            )
        
        # Check Redis
        try:
            from infrastructure.cache import cache
            cache.redis.ping()
            health["checks"]["redis"] = "healthy"
        except Exception as e:
            health["checks"]["redis"] = "unhealthy"
            health["status"] = "degraded"
            AlertManager.send_alert(
                severity=AlertManager.SEVERITY_WARNING,
                message=f"Redis health check failed: {e}",
                component="redis"
            )
        
        # Check Celery workers
        try:
            from infrastructure.tasks import celery_app
            stats = celery_app.control.inspect().stats()
            if not stats:
                health["checks"]["celery"] = "no_workers"
                health["status"] = "degraded"
                AlertManager.send_alert(
                    severity=AlertManager.SEVERITY_CRITICAL,
                    message="No Celery workers available",
                    component="celery"
                )
            else:
                health["checks"]["celery"] = "healthy"
        except Exception as e:
            health["checks"]["celery"] = "unhealthy"
            health["status"] = "degraded"
            AlertManager.send_alert(
                severity=AlertManager.SEVERITY_ERROR,
                message=f"Celery health check failed: {e}",
                component="celery"
            )
        
        return health


# Global instances
alert_manager = AlertManager()
structured_logger = StructuredLogger()
tracing_manager = TracingManager()


# ==================== METRICS ENDPOINT ====================

def get_metrics():
    """Get Prometheus metrics"""
    return generate_latest()
