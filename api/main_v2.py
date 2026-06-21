"""
Production-Grade API Implementation
Integrates authentication, validation, monitoring, caching, and reliability
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List, Optional
import time
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

# Security & Auth
from auth.security import (
    get_current_user, require_user, require_admin,
    rate_limit_strict, rate_limit_normal, TokenData
)
from auth.validation import (
    JobSearchRequest, ResumeGenerationRequest,
    ApplicationRequest, PaginationParams
)

# Infrastructure
from infrastructure.monitoring import (
    structured_logger, http_requests_total,
    get_metrics, alert_manager
)
from infrastructure.cache import cache, JobSearchCache
from infrastructure.tasks import celery_app, TaskResult
from infrastructure.reliability import (
    retry, timeout,
    api_circuit_breaker, scraping_bulkhead
)

# Database
from models.database import get_db, Job, Application, Resume

def _get_cors_origins() -> list:
    origins_env = os.environ.get("CORS_ORIGINS", "")
    if origins_env:
        return [o.strip() for o in origins_env.split(",") if o.strip()]
    if os.environ.get("ENVIRONMENT", "development") == "production":
        import warnings
        warnings.warn("CORS_ORIGINS not set in production — defaulting to empty list", RuntimeWarning)
        return []
    return ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000"]


@asynccontextmanager
async def lifespan(app):
    _logger.info("API server starting up")
    try:
        cache.redis.ping()
        _logger.info("Redis connection established")
    except Exception as e:
        _logger.error("Redis connection failed: %s", e)
    yield
    _logger.info("API server shutting down")


# App initialization
app = FastAPI(
    title="AI Job Agent API",
    description="Production-grade AI job application automation system",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ==================== MIDDLEWARE ====================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    structured_logger.log_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration=duration,
    )
    return response


# Error handling middleware
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    structured_logger.log_error(
        error_type="unhandled_exception",
        component="api",
        message=str(exc),
        exception=exc
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if app.debug else "An error occurred",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


# ==================== HEALTH & MONITORING ====================

@app.get("/health", tags=["System"])
async def health_check():
    """
    Comprehensive health check endpoint
    Checks database, Redis, Celery workers
    """
    health = alert_manager.check_system_health()
    
    status_code = 200 if health["status"] == "healthy" else 503
    
    return JSONResponse(
        status_code=status_code,
        content={
            **health,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


@app.get("/metrics", tags=["System"])
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(
        content=get_metrics(),
        media_type="text/plain"
    )


@app.get("/", tags=["System"])
async def root():
    """API root endpoint"""
    return {
        "name": "AI Job Agent API",
        "version": "2.0.0",
        "status": "online",
        "docs": "/api/docs",
        "health": "/health",
        "metrics": "/metrics"
    }


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/auth/token", tags=["Authentication"])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Login — verifies credentials against DB and returns a JWT."""
    from models.database import User
    from auth.security import create_access_token
    import bcrypt as _bcrypt, hashlib as _hl

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not bool(user.is_active):
        raise HTTPException(status_code=401, detail="Invalid username or password",
                            headers={"WWW-Authenticate": "Bearer"})

    stored: str = str(user.hashed_password or "")
    valid: bool = False
    if stored.startswith("$2"):
        try:
            valid = _bcrypt.checkpw(form_data.password.encode(), stored.encode())
        except Exception:
            valid = False
    else:
        valid = stored == _hl.sha256((form_data.password + "salt_for_dev_only").encode()).hexdigest()

    if not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password",
                            headers={"WWW-Authenticate": "Bearer"})

    access_token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "roles": getattr(user, "roles", None) or ["user"],
    })
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/auth/me", tags=["Authentication"])
async def get_current_user_info(current_user: TokenData = Depends(get_current_user)):
    """Get current user information"""
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "roles": current_user.roles
    }


# ==================== JOB SEARCH ENDPOINTS ====================

@app.post("/api/jobs/search", tags=["Jobs"], dependencies=[Depends(require_user)])
@retry(max_attempts=3)
@timeout(30.0)
async def search_jobs(
    request: JobSearchRequest,
    current_user: TokenData = Depends(get_current_user),
    rate_limit: TokenData = Depends(rate_limit_normal),
    db: Session = Depends(get_db)
):
    """
    Search for jobs across platforms
    With caching, rate limiting, and monitoring
    """
    # Check cache first
    cached_jobs = JobSearchCache.get_jobs(
        query=request.query,
        location=request.location or "",
        remote=request.remote or False,
        limit=request.limit or 50
    )
    
    if cached_jobs:
        return {
            "jobs": cached_jobs,
            "cached": True,
            "count": len(cached_jobs)
        }
    
    # Submit async task
    from workers.job_search import search_jobs_task
    
    task = search_jobs_task.delay(
        query=request.query,
        location=request.location,
        remote=request.remote,
        limit=request.limit,
        user_id=current_user.user_id
    )
    
    return {
        "task_id": task.id,
        "status": "processing",
        "message": "Job search initiated. Use /api/tasks/{task_id} to check status"
    }


_VALID_JOB_SORT_FIELDS = {"id", "title", "company", "location", "match_score", "scraped_at", "platform"}


@app.get("/api/jobs", tags=["Jobs"], dependencies=[Depends(require_user)])
async def list_jobs(
    pagination: PaginationParams = Depends(),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List jobs with pagination"""
    offset = (pagination.page - 1) * pagination.page_size

    query = db.query(Job)

    if pagination.sort_by:
        if pagination.sort_by not in _VALID_JOB_SORT_FIELDS:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid sort_by '{pagination.sort_by}'. Allowed: {sorted(_VALID_JOB_SORT_FIELDS)}"
            )
        col = getattr(Job, pagination.sort_by)
        query = query.order_by(col.desc() if pagination.sort_order == "desc" else col.asc())
    
    total = query.count()
    jobs = query.offset(offset).limit(pagination.page_size).all()
    
    return {
        "jobs": [job.to_dict() for job in jobs],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        "total_pages": (total + pagination.page_size - 1) // pagination.page_size
    }


@app.get("/api/jobs/{job_id}", tags=["Jobs"], dependencies=[Depends(require_user)])
async def get_job(
    job_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific job details"""
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    
    return job.to_dict()


# ==================== RESUME ENDPOINTS ====================

@app.post("/api/resumes/generate", tags=["Resumes"], dependencies=[Depends(require_user)])
async def generate_resume(
    request: ResumeGenerationRequest,
    current_user: TokenData = Depends(get_current_user),
    rate_limit: TokenData = Depends(rate_limit_normal),
    db: Session = Depends(get_db)
):
    """
    Generate ATS-optimized resume for job
    Idempotent - won't regenerate if already created
    """
    from workers.resume_generation import generate_resume_task
    
    task = generate_resume_task.delay(
        job_id=request.job_id,
        variant=request.variant,
        user_id=current_user.user_id,
        custom_skills=request.custom_skills
    )
    
    return {
        "task_id": task.id,
        "status": "processing",
        "message": "Resume generation initiated"
    }


@app.get("/api/resumes", tags=["Resumes"], dependencies=[Depends(require_user)])
async def list_resumes(
    pagination: PaginationParams = Depends(),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's generated resumes"""
    offset = (pagination.page - 1) * pagination.page_size
    
    query = db.query(Resume).filter(Resume.user_id == current_user.user_id)
    
    total = query.count()
    resumes = query.offset(offset).limit(pagination.page_size).all()
    
    return {
        "resumes": [r.to_dict() for r in resumes],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size
    }


# ==================== APPLICATION ENDPOINTS ====================

@app.post("/api/applications/submit", tags=["Applications"], dependencies=[Depends(require_user)])
async def submit_application(
    request: ApplicationRequest,
    current_user: TokenData = Depends(get_current_user),
    rate_limit: TokenData = Depends(rate_limit_strict),  # Strict limit for submissions
    db: Session = Depends(get_db)
):
    """
    Submit job application
    Idempotent - prevents duplicate submissions
    """
    # Check if already applied
    existing = db.query(Application).filter(
        Application.job_id == request.job_id,
        Application.user_id == current_user.user_id
    ).first()
    
    if existing:
        return {
            "status": "already_applied",
            "application_id": existing.id,
            "submitted_at": existing.created_at.isoformat()
        }
    
    # Submit async task
    from workers.application_submission import submit_application_task
    
    task = submit_application_task.delay(
        job_id=request.job_id,
        resume_id=request.resume_id,
        cover_letter_id=request.cover_letter_id,
        user_id=current_user.user_id
    )
    
    return {
        "task_id": task.id,
        "status": "processing",
        "message": "Application submission initiated"
    }


@app.get("/api/applications", tags=["Applications"], dependencies=[Depends(require_user)])
async def list_applications(
    pagination: PaginationParams = Depends(),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's applications"""
    offset = (pagination.page - 1) * pagination.page_size
    
    query = db.query(Application).filter(Application.user_id == current_user.user_id)
    
    total = query.count()
    applications = query.offset(offset).limit(pagination.page_size).all()
    
    return {
        "applications": [a.to_dict() for a in applications],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size
    }


# ==================== ANALYTICS ENDPOINTS ====================

@app.get("/api/analytics/dashboard", tags=["Analytics"], dependencies=[Depends(require_user)])
async def get_dashboard_stats(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get dashboard analytics"""
    from sqlalchemy import func
    
    # Jobs scraped
    total_jobs = db.query(func.count(Job.id)).scalar()
    
    # Applications submitted
    total_apps = db.query(func.count(Application.id)).filter(
        Application.user_id == current_user.user_id
    ).scalar()
    
    # Interview rate
    interviews = db.query(func.count(Application.id)).filter(
        Application.user_id == current_user.user_id,
        Application.status == "interview"
    ).scalar()
    
    interview_rate = (interviews / total_apps * 100) if total_apps > 0 else 0
    
    # Average ATS score
    avg_ats_score = db.query(func.avg(Resume.ats_score)).filter(
        Resume.user_id == current_user.user_id
    ).scalar() or 0
    
    return {
        "total_jobs": total_jobs,
        "total_applications": total_apps,
        "interview_invitations": interviews,
        "interview_rate": round(interview_rate, 2),
        "average_ats_score": round(avg_ats_score, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/analytics/costs", tags=["Analytics"], dependencies=[Depends(require_admin)])
async def get_cost_analytics(current_user: TokenData = Depends(get_current_user)):
    """Get LLM cost analytics (admin only)"""
    from infrastructure.ai_management import cost_tracker
    
    return {
        "total_cost_30d": cost_tracker.get_total_cost(days=30),
        "cost_by_model": cost_tracker.get_cost_by_model(days=30),
        "cache_savings": cost_tracker.get_cache_savings(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ==================== TASK STATUS ENDPOINTS ====================

@app.get("/api/tasks/{task_id}", tags=["Tasks"], dependencies=[Depends(require_user)])
async def get_task_status(
    task_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get status of async task"""
    status = TaskResult.get_status(task_id)
    return status


# ==================== ADMIN ENDPOINTS ====================

@app.post("/api/admin/queue/purge", tags=["Admin"], dependencies=[Depends(require_admin)])
async def purge_queue(
    queue_name: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Purge all tasks from queue (admin only)"""
    from infrastructure.tasks import QueueManager
    
    count = QueueManager.purge_queue(queue_name)
    
    return {
        "queue": queue_name,
        "purged_count": count,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/admin/workers", tags=["Admin"], dependencies=[Depends(require_admin)])
async def get_worker_stats(current_user: TokenData = Depends(get_current_user)):
    """Get Celery worker statistics (admin only)"""
    from infrastructure.tasks import QueueManager
    
    stats = QueueManager.get_worker_stats()
    
    return {
        "workers": stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ==================== STARTUP/SHUTDOWN ====================
# Startup and shutdown logic is handled by the lifespan context manager above.


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "api.main_v2:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
