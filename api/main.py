"""
FastAPI Backend - REST API for AI Job Agent
Provides endpoints for dashboard and external integrations
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import sessionmaker
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from pydantic import field_validator, BaseModel, ConfigDict

from config.settings import settings
# Auth & monitoring — wired into running API (FIX 3 & FIX 4)
from auth.security import get_current_user, TokenData, login_rate_limiter, strict_ip_limiter
from infrastructure.reliability import api_circuit_breaker
from fastapi.security import OAuth2PasswordRequestForm
from infrastructure.monitoring import (
    structured_logger, http_requests_total,
    http_request_duration, get_metrics
)
from prometheus_client import CONTENT_TYPE_LATEST

from models.database import Base, Job, Application, ResumeVersion, UserProfile, Analytics, ActivityLog
from utils.logger import logger


# Initialize FastAPI
@asynccontextmanager
async def lifespan(app):
    """Application lifespan — replaces deprecated on_event handlers."""
    logger.info("🚀 API Server starting...")
    logger.info(f"   Environment: {settings.environment.value}")
    logger.info(f"   Debug mode: {settings.debug}")
    yield
    logger.info("👋 API Server shutting down...")

def _get_cors_origins() -> list:
    """Load CORS origins from env — defaults to localhost for dev."""
    origins_env = os.environ.get("CORS_ORIGINS", "")
    if origins_env:
        return [o.strip() for o in origins_env.split(",") if o.strip()]
    if os.environ.get("ENVIRONMENT", "development") == "production":
        # In production with no CORS_ORIGINS set, warn loudly but don't crash
        import warnings
        warnings.warn("CORS_ORIGINS not set in production — defaulting to empty list", RuntimeWarning)
        return []
    return ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000"]


app = FastAPI(lifespan=lifespan, 
    title="AI Job Agent API",
    description="Autonomous job application system API",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup — delegate to models.database so all modules (API, workers,
# tests) share ONE engine/session source of truth. This also means
# models.database._get_engine() can be reset (e.g. in tests) and get_db()
# picks up the change immediately, instead of using a stale engine captured
# at import time via settings.database_url.
from models.database import get_db  # noqa: F401  (re-exported for endpoints)


# =============================================================================
# PYDANTIC MODELS (Request/Response schemas)
# =============================================================================

class JobResponse(BaseModel):
    id: str

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v):
        return str(v)
    title: str
    company: str
    location: str
    platform: str
    url: str
    remote: bool
    salary_min: Optional[int]
    salary_max: Optional[int]
    match_score: Optional[float]
    applied: bool
    scraped_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ApplicationResponse(BaseModel):
    id: str
    job_id: str
    job_title: str
    company: str
    platform: str
    status: str
    applied_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AnalyticsResponse(BaseModel):
    total_jobs_scraped: int
    total_applications: int
    interviews_scheduled: int
    offers_received: int
    success_rate: float
    avg_response_time_days: Optional[float]
    

class DashboardStats(BaseModel):
    today_applications: int
    week_applications: int
    month_applications: int
    pending_applications: int
    interview_rate: float
    best_platform: str
    


@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    """Emit Prometheus metrics + structured log on every request."""
    import time
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    endpoint = request.url.path
    method = request.method
    status = str(response.status_code)
    try:
        http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        http_request_duration.labels(method=method, endpoint=endpoint).observe(duration)
        structured_logger.log_request(method=method, endpoint=endpoint, status=int(status), duration=duration)
    except Exception:
        pass  # Never let monitoring break the response
    return response


# =============================================================================
# ENDPOINTS
# =============================================================================


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "online",
        "service": "AI Job Agent API",
        "version": "1.0.0",
        "environment": settings.environment.value
    }


@app.get("/health")
async def health():
    """Kubernetes liveness/readiness probe"""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=get_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/token")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    _rate: None = Depends(login_rate_limiter)):
    """Issue JWT token. Verifies credentials against User table in all environments."""
    from auth.security import create_access_token
    from models.database import User
    import bcrypt as _bcrypt, hashlib as _hl
    import os

    db_gen = get_db()
    db = next(db_gen)
    try:
        user = db.query(User).filter(User.username == form_data.username).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Verify password — support both bcrypt and SHA-256 (dev fallback)
        pw = form_data.password
        stored = user.hashed_password or ""
        valid = False
        if stored.startswith("$2"):  # bcrypt hash
            try:
                valid = _bcrypt.checkpw(pw.encode(), stored.encode())
            except Exception:
                valid = False
        else:  # SHA-256 fallback (dev environments)
            valid = stored == _hl.sha256((pw + "salt_for_dev_only").encode()).hexdigest()

        if not valid:
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    finally:
        try: next(db_gen)
        except StopIteration: pass

    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "roles": user.roles or ["user"],
    })
    return {"access_token": token, "token_type": "bearer"}



@app.post("/auth/register", status_code=201)
async def register(
    request: Request,
    username: str,
    password: str,
    email: str,
    _rate: None = Depends(login_rate_limiter),
    db: Session = Depends(get_db)):
    """Create a new user. Returns JWT token immediately."""
    from models.database import User
    from auth.security import create_access_token
    import hashlib as _hl

    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    try:
        # Try bcrypt directly (faster, doesn't use passlib's version check)
        import bcrypt as _bcrypt
        hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    except Exception:
        # SHA-256 fallback for environments where bcrypt is unavailable
        hashed = _hl.sha256((password + "salt_for_dev_only").encode()).hexdigest()

    user = User(username=username, email=email, hashed_password=hashed,
                roles=["user"], is_active=True)
    db.add(user); db.commit(); db.refresh(user)

    token = create_access_token({"sub": str(user.id), "username": user.username,
                                  "roles": user.roles})
    return {"access_token": token, "token_type": "bearer",
            "user_id": str(user.id), "username": user.username}



@app.get("/api/jobs", response_model=List[JobResponse])
async def get_jobs(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    _rl: None = Depends(strict_ip_limiter),
    skip: int = 0,
    limit: int = 50,
    platform: Optional[str] = None,
    remote_only: bool = False,
    min_score: Optional[float] = None,
    applied: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    Get list of jobs with filters
    
    Query params:
    - skip: Pagination offset
    - limit: Max results
    - platform: Filter by platform (linkedin, indeed, etc.)
    - remote_only: Only remote jobs
    - min_score: Minimum match score
    - applied: Filter by application status
    """
    query = db.query(Job)
    
    if platform:
        query = query.filter(Job.platform == platform)
    
    if remote_only:
        query = query.filter(Job.remote == True)
    
    if min_score is not None:
        query = query.filter(Job.match_score >= min_score)
    
    if applied is not None:
        query = query.filter(Job.applied == applied)
    
    jobs = query.order_by(desc(Job.scraped_at)).offset(skip).limit(limit).all()
    
    return jobs


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: TokenData = Depends(get_current_user),
     db: Session = Depends(get_db)):
    """Get single job by ID"""
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job


@app.get("/api/applications", response_model=List[ApplicationResponse])
async def get_applications(
    current_user: TokenData = Depends(get_current_user),
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get list of applications with filters
    
    Query params:
    - status: Filter by status (pending, submitted, interviewing, etc.)
    - platform: Filter by platform
    """
    query = db.query(Application)
    
    if status:
        query = query.filter(Application.status == status)
    
    if platform:
        query = query.filter(Application.platform == platform)
    
    applications = query.order_by(desc(Application.applied_at)).offset(skip).limit(limit).all()
    
    # Enrich with job details
    result = []
    for app in applications:
        job = db.query(Job).filter(Job.id == app.job_id).first()
        result.append({
            "id": str(app.id),
            "job_id": str(app.job_id),
            "job_title": job.title if job else "Unknown",
            "company": job.company if job else "Unknown",
            "platform": app.platform,
            "status": app.status.value,
            "applied_at": app.applied_at
        })
    
    return result


@app.get("/api/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    current_user: TokenData = Depends(get_current_user),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    Get analytics for last N days
    
    Query params:
    - days: Number of days to analyze (1-365)
    """
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Total jobs scraped
    total_jobs = db.query(func.count(Job.id)).filter(
        Job.scraped_at >= start_date
    ).scalar()
    
    # Total applications
    total_apps = db.query(func.count(Application.id)).filter(
        Application.applied_at >= start_date
    ).scalar()
    
    # Interviews
    interviews = db.query(func.count(Application.id)).filter(
        Application.applied_at >= start_date,
        Application.status == 'interviewing'
    ).scalar()
    
    # Offers
    offers = db.query(func.count(Application.id)).filter(
        Application.applied_at >= start_date,
        Application.offer_received == True
    ).scalar()
    
    # Success rate
    viewed_apps = db.query(func.count(Application.id)).filter(
        Application.applied_at >= start_date,
        Application.status.in_(['viewed', 'interviewing', 'offer'])
    ).scalar()
    
    success_rate = (viewed_apps / total_apps * 100) if total_apps > 0 else 0
    
    # Average response time
    responses = db.query(
        func.avg(
            func.extract('epoch', Application.response_date - Application.applied_at) / 86400
        )
    ).filter(
        Application.applied_at >= start_date,
        Application.response_date.isnot(None)
    ).scalar()
    
    return {
        "total_jobs_scraped": total_jobs or 0,
        "total_applications": total_apps or 0,
        "interviews_scheduled": interviews or 0,
        "offers_received": offers or 0,
        "success_rate": round(success_rate, 2),
        "avg_response_time_days": round(responses, 1) if responses else None
    }


@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)):
    """Get key stats for dashboard"""
    
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    
    # Applications counts
    today_apps = db.query(func.count(Application.id)).filter(
        Application.applied_at >= today_start
    ).scalar() or 0
    
    week_apps = db.query(func.count(Application.id)).filter(
        Application.applied_at >= week_start
    ).scalar() or 0
    
    month_apps = db.query(func.count(Application.id)).filter(
        Application.applied_at >= month_start
    ).scalar() or 0
    
    # Pending applications
    pending = db.query(func.count(Application.id)).filter(
        Application.status == 'pending'
    ).scalar() or 0
    
    # Interview rate
    total = month_apps
    interviews = db.query(func.count(Application.id)).filter(
        Application.applied_at >= month_start,
        Application.status == 'interviewing'
    ).scalar() or 0
    
    interview_rate = (interviews / total * 100) if total > 0 else 0
    
    # Best performing platform
    platform_stats = db.query(
        Application.platform,
        func.count(Application.id).label('count')
    ).filter(
        Application.applied_at >= month_start
    ).group_by(Application.platform).order_by(desc('count')).first()
    
    best_platform = platform_stats[0] if platform_stats else "N/A"
    
    return {
        "today_applications": today_apps,
        "week_applications": week_apps,
        "month_applications": month_apps,
        "pending_applications": pending,
        "interview_rate": round(interview_rate, 2),
        "best_platform": best_platform
    }


@app.get("/api/resume-versions")
async def get_resume_versions(
    current_user: TokenData = Depends(get_current_user),
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Get resume versions with performance stats"""
    versions = db.query(ResumeVersion).order_by(
        desc(ResumeVersion.created_at)
    ).limit(limit).all()
    
    result = []
    for version in versions:
        result.append({
            "id": str(version.id),
            "variant_type": version.variant_type,
            "ats_score": version.ats_score_estimate,
            "used_count": version.used_count,
            "success_rate": version.success_rate or 0,
            "created_at": version.created_at.isoformat()
        })
    
    return result


@app.get("/api/activity-log")
async def get_activity_log(
    current_user: TokenData = Depends(get_current_user),
    limit: int = 100,
    activity_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get recent activity logs"""
    query = db.query(ActivityLog)
    
    if activity_type:
        query = query.filter(ActivityLog.activity_type == activity_type)
    
    logs = query.order_by(desc(ActivityLog.timestamp)).limit(limit).all()
    
    return [
        {
            "id": str(log.id),
            "timestamp": log.timestamp.isoformat(),
            "activity_type": log.activity_type,
            "status": log.status,
            "details": log.details,
            "duration_seconds": log.duration_seconds
        }
        for log in logs
    ]



@app.post("/api/jobs/{job_id}/apply", status_code=202)
async def apply_to_job(
    request: Request,
    job_id: str,
    current_user: TokenData = Depends(get_current_user),
    _rl: None = Depends(strict_ip_limiter),
    db: Session = Depends(get_db)):
    """Submit a job application via async Celery worker. Returns 202 immediately."""
    import uuid as _uuid
    try:
        _jid = _uuid.UUID(str(job_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid job_id format")

    job = db.query(Job).filter(Job.id == _jid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = db.query(Application).filter(
        Application.job_id == job.id,
        Application.user_id == current_user.user_id
    ).first()
    if existing:
        return {
            "status": "already_applied",
            "application_id": str(existing.id),
            "applied_at": existing.applied_at.isoformat() if existing.applied_at else None,
        }

    try:
        from workers.application_submission import submit_application_task

        @api_circuit_breaker
        def _dispatch():
            """Wrapped in circuit breaker — opens after 5 consecutive failures."""
            return submit_application_task.delay(
                job_id=str(job.id), resume_id=None,
                cover_letter_id=None, user_id=current_user.user_id,
            )

        task = _dispatch()
        return {"status": "queued", "task_id": task.id,
                "message": "Application dispatched to worker queue."}
    except Exception:
        from models.database import ApplicationStatus
        from datetime import datetime, timezone
        application = Application(
            job_id=job.id, user_id=current_user.user_id,
            platform=job.platform, status=ApplicationStatus.PENDING,
            applied_at=datetime.now(timezone.utc),
        )
        db.add(application); job.applied = True; db.commit()
        return {"status": "queued_sync", "application_id": str(application.id),
                "message": "Applied synchronously (worker queue unavailable)."}


@app.get("/api/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: TokenData = Depends(get_current_user)):
    """Poll Celery task status."""
    try:
        from infrastructure.tasks import celery_app
        result = celery_app.AsyncResult(task_id)
        return {"task_id": task_id, "status": result.status,
                "result": result.result if result.ready() else None}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Task queue unavailable: {e}")


@app.get("/api/download/resume/{version_id}")
async def download_resume(
    version_id: str,
    current_user: TokenData = Depends(get_current_user),
     db: Session = Depends(get_db)):
    """Download a specific resume version"""
    version = db.query(ResumeVersion).filter(ResumeVersion.id == version_id).first()
    
    if not version or not version.resume_file_path:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    return FileResponse(
        version.resume_file_path,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        filename=f'resume_{version.variant_type}.docx'
    )


# =============================================================================
# STARTUP/SHUTDOWN
# =============================================================================



# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.reload,
        log_level="info"
    )
