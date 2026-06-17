"""
Database Models for AI Job Agent
Using SQLAlchemy ORM with PostgreSQL
"""

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey, Enum
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
import enum


Base = declarative_base()


class JobStatus(str, enum.Enum):
    """Job listing status"""
    NEW = "new"
    SCORED = "scored"
    APPLIED = "applied"
    REJECTED = "rejected"


class ApplicationStatus(str, enum.Enum):
    """Application status tracking"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    INTERVIEWING = "interviewing"
    REJECTED = "rejected"
    OFFER = "offer"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class Job(Base):
    """Job listing model"""
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Platform info
    platform = Column(String(50), nullable=False, index=True)
    platform_job_id = Column(String(255), unique=True)
    url = Column(Text, unique=True, nullable=False)
    
    # Job details
    title = Column(String(255), nullable=False, index=True)
    company = Column(String(255), nullable=False, index=True)
    location = Column(String(255))
    
    # Compensation
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    currency = Column(String(10), default="USD")
    
    # Job type
    job_type = Column(String(50))  # full_time, part_time, contract, internship
    remote = Column(Boolean, default=False, index=True)
    hybrid = Column(Boolean, default=False)
    
    # Content
    description = Column(Text)
    requirements = Column(Text)
    benefits = Column(Text)
    
    # Metadata
    scraped_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    posted_date = Column(DateTime)
    expires_at = Column(DateTime)
    
    # AI scoring
    match_score = Column(Float)  # 0-100
    ai_analysis = Column(JSON)  # Stores AI agent's detailed analysis
    keywords = Column(JSON)  # Extracted keywords
    
    # Status
    status = Column(Enum(JobStatus), default=JobStatus.NEW, index=True)
    applied = Column(Boolean, default=False, index=True)
    
    # Additional data
    company_info = Column(JSON)  # Company size, funding, etc.
    tech_stack = Column(JSON)  # Technologies mentioned
    
    # Relationships
    applications = relationship("Application", back_populates="job")
    
    def __repr__(self):
        return f"<Job {self.title} at {self.company}>"


class Application(Base):
    """Application tracking model"""
    __tablename__ = "applications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign keys
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    user_id = Column(String(255), index=True)  # Who submitted the application
    resume_version_id = Column(UUID(as_uuid=True), ForeignKey("resume_versions.id"))
    
    # Application details
    applied_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    platform = Column(String(50), nullable=False, index=True)
    platform_application_id = Column(String(255))
    
    # Documents submitted
    resume_path = Column(Text)
    cover_letter_text = Column(Text)
    cover_letter_path = Column(Text)
    
    # Screening questions
    screening_questions = Column(JSON)  # Questions and answers
    
    # Status tracking
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.PENDING, index=True)
    response_date = Column(DateTime)
    rejection_reason = Column(Text)
    
    # Interview tracking
    interview_date = Column(DateTime)
    interview_type = Column(String(50))  # phone, video, onsite
    interview_notes = Column(Text)
    
    # Offer tracking
    offer_received = Column(Boolean, default=False)
    offer_amount = Column(Integer)
    offer_currency = Column(String(10))
    offer_date = Column(DateTime)
    
    # Evidence
    screenshots = Column(JSON)  # Array of screenshot URLs
    confirmation_email = Column(Text)
    
    # Metadata
    notes = Column(Text)
    submission_method = Column(String(50))  # automated, manual, easy_apply
    
    # Relationships
    job = relationship("Job", back_populates="applications")
    resume_version = relationship("ResumeVersion", back_populates="applications")
    
    def __repr__(self):
        return f"<Application {self.job.title} - {self.status}>"


class ResumeVersion(Base):
    """Resume version tracking for A/B testing"""
    __tablename__ = "resume_versions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Resume content
    base_resume_text = Column(Text, nullable=False)
    tailored_resume_text = Column(Text, nullable=False)
    resume_file_path = Column(Text)
    
    # Optimization details
    variant_type = Column(String(50))  # conservative, balanced, aggressive
    keywords_added = Column(JSON)
    keywords_removed = Column(JSON)
    changes_made = Column(JSON)
    
    # ATS scoring
    ats_score_estimate = Column(Float)
    keyword_density = Column(Float)
    readability_score = Column(Float)
    
    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    created_for_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    
    # Performance metrics
    used_count = Column(Integer, default=0)
    viewed_count = Column(Integer, default=0)
    interview_count = Column(Integer, default=0)
    offer_count = Column(Integer, default=0)
    success_rate = Column(Float)  # Calculated: interviews / applications
    
    # Relationships
    applications = relationship("Application", back_populates="resume_version")
    
    def __repr__(self):
        return f"<ResumeVersion {self.variant_type} - Score: {self.ats_score_estimate}>"


class UserProfile(Base):
    """User profile and preferences"""
    __tablename__ = "user_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Personal info
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50))
    location = Column(String(255))
    
    # Professional links
    linkedin_url = Column(Text)
    github_url = Column(Text)
    portfolio_url = Column(Text)
    
    # Job preferences
    target_roles = Column(JSON)  # Array of role titles
    skills_primary = Column(JSON)
    skills_secondary = Column(JSON)
    
    # Location preferences
    preferred_locations = Column(JSON)
    willing_to_relocate = Column(JSON)
    remote_preference = Column(String(50))  # required, preferred, no_preference
    
    # Compensation
    minimum_salary_usd = Column(Integer)
    minimum_salary_inr = Column(Integer)
    currency_preference = Column(String(10))
    
    # Work authorization
    work_authorization = Column(JSON)  # Countries where authorized
    visa_sponsorship_required = Column(Boolean, default=False)
    
    # Preferences
    experience_level = Column(String(50))
    company_size_pref = Column(JSON)
    company_stage_pref = Column(JSON)
    
    # Base documents
    base_resume_path = Column(Text)
    base_cover_letter_template = Column(Text)
    
    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f"<UserProfile {self.full_name}>"


class ActivityLog(Base):
    """System activity logging"""
    __tablename__ = "activity_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Activity details
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    activity_type = Column(String(50), index=True)  # search, score, optimize, apply
    platform = Column(String(50))
    
    # Status
    status = Column(String(50))  # success, failed, pending
    error_message = Column(Text)
    
    # Metadata
    details = Column(JSON)
    duration_seconds = Column(Float)
    
    def __repr__(self):
        return f"<ActivityLog {self.activity_type} - {self.status}>"


class Analytics(Base):
    """Daily analytics aggregation"""
    __tablename__ = "analytics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Date
    date = Column(DateTime, nullable=False, unique=True, index=True)
    
    # Counts
    jobs_scraped = Column(Integer, default=0)
    jobs_scored = Column(Integer, default=0)
    applications_submitted = Column(Integer, default=0)
    applications_viewed = Column(Integer, default=0)
    interviews_scheduled = Column(Integer, default=0)
    offers_received = Column(Integer, default=0)
    
    # Success metrics
    application_success_rate = Column(Float)  # viewed / submitted
    interview_rate = Column(Float)  # interviews / submitted
    offer_rate = Column(Float)  # offers / interviews
    
    # Platform breakdown
    platform_stats = Column(JSON)
    
    # Resume performance
    best_resume_variant = Column(String(50))
    avg_ats_score = Column(Float)
    
    # Cost tracking
    total_cost_usd = Column(Float, default=0.0)
    llm_api_calls = Column(Integer, default=0)
    
    def __repr__(self):
        return f"<Analytics {self.date.date()} - {self.applications_submitted} apps>"


# Database initialization
def init_database(engine=None, use_alembic: bool = True):
    """
    Initialize database.
    Production: uses Alembic migrations (use_alembic=True, default).
    Development/test: falls back to create_all when Alembic unavailable.
    """
    import os
    env = os.getenv("ENVIRONMENT", "development")

    if use_alembic and env != "test":
        try:
            from alembic.config import Config
            from alembic import command as alembic_cmd
            alembic_cfg = Config("alembic.ini")
            alembic_cmd.upgrade(alembic_cfg, "head")
            return
        except Exception as e:
            import warnings
            warnings.warn(f"Alembic migration failed ({e}), falling back to create_all. "
                          "Fix migrations before deploying to production.", RuntimeWarning)

    # Fallback: create_all for dev/test or when Alembic unavailable
    if engine is None:
        engine = _get_engine()
    Base.metadata.create_all(engine)
    print("✓ Database tables created")


def get_analytics_summary(session, days: int = 7):
    """Get analytics summary for last N days"""
    from datetime import timedelta
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    analytics = session.query(Analytics).filter(
        Analytics.date >= start_date
    ).all()
    
    if not analytics:
        return None
    
    return {
        "total_applications": sum(a.applications_submitted for a in analytics),
        "total_interviews": sum(a.interviews_scheduled for a in analytics),
        "total_offers": sum(a.offers_received for a in analytics),
        "avg_interview_rate": sum(a.interview_rate for a in analytics if a.interview_rate) / len(analytics),
        "total_cost": sum(a.total_cost_usd for a in analytics)
    }


# ==================== MISSING MODELS (added to fix broken imports) ====================

class Resume(Base):
    """Generated resume storage"""
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    variant = Column(String(50), default="balanced")
    content = Column(Text, nullable=False)
    file_path = Column(Text)
    ats_score = Column(Float, default=0.0)
    keyword_match = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "job_id": str(self.job_id) if self.job_id else None,
            "variant": self.variant,
            "ats_score": self.ats_score,
            "keyword_match": self.keyword_match,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """Application user accounts"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    roles = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    location = Column(String(255))
    target_roles = Column(JSON, default=list)
    remote_preference = Column(Boolean, default=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "roles": self.roles,
            "is_active": self.is_active,
        }


# ==================== to_dict() for existing models ====================

def _job_to_dict(self):
    return {
        "id": str(self.id),
        "platform": self.platform,
        "title": self.title,
        "company": self.company,
        "location": self.location,
        "url": self.url,
        "remote": self.remote,
        "salary_min": self.salary_min,
        "salary_max": self.salary_max,
        "match_score": self.match_score,
        "applied": self.applied,
        "status": self.status.value if self.status else None,
        "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
    }

def _application_to_dict(self):
    return {
        "id": str(self.id),
        "job_id": str(self.job_id),
        "platform": self.platform,
        "status": self.status.value if self.status else None,
        "applied_at": self.applied_at.isoformat() if self.applied_at else None,
        "offer_received": self.offer_received,
    }

Job.to_dict = _job_to_dict
Application.to_dict = _application_to_dict


# ==================== DB SESSION HELPERS ====================

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
        is_sqlite = db_url.startswith("sqlite")
        kwargs = {
            "connect_args": {"check_same_thread": False} if is_sqlite else {},
        }
        if is_sqlite:
            # NullPool avoids stale-connection / "readonly database" issues
            # when the engine is rebuilt to point at a different SQLite file
            # within the same process (common in test suites).
            from sqlalchemy.pool import NullPool
            kwargs["poolclass"] = NullPool
        if not is_sqlite:
            # Production PostgreSQL connection pooling
            kwargs.update({
                "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
                "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
                "pool_pre_ping": True,   # Detect stale connections
                "pool_recycle": 3600,    # Recycle every hour
            })
        _engine = create_engine(db_url, **kwargs)
    return _engine


def SessionLocal():
    """Return a new DB session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal()


def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
