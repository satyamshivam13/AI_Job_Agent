"""
Production-Grade Celery Workers
Implements job search, resume generation, and application submission with full monitoring
"""

from celery import Task
from infrastructure.tasks import celery_app, BaseTask
from infrastructure.monitoring import structured_logger
from infrastructure.cache import JobSearchCache, LLMCache
from infrastructure.ai_management import model_router, quality_evaluator, cost_tracker
from infrastructure.reliability import retry, timeout, idempotent, scraping_bulkhead
from typing import List, Dict, Any, Optional
import asyncio
from datetime import datetime, timezone


# ==================== JOB SEARCH WORKER ====================

@celery_app.task(
    base=BaseTask,
    bind=True,
    name="workers.job_search.search_jobs_task"
)
def search_jobs_task(
    self,
    query: str,
    location: Optional[str] = None,
    remote: bool = False,
    limit: int = 50,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for jobs across platforms with caching and monitoring
    """
    start_time = datetime.now(timezone.utc)
    
    try:
        # Run async search
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        jobs = loop.run_until_complete(
            _search_jobs_async(query, location, remote, limit, user_id)
        )
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Log success
        structured_logger.log_job_search(
            platform="multi_platform",
            query=query,
            jobs_found=len(jobs),
            duration=duration,
            status="success"
        )
        
        # Cache results
        JobSearchCache.set_jobs(query, location or "", remote, limit, jobs)
        
        return {
            "status": "success",
            "jobs": jobs,
            "count": len(jobs),
            "duration": duration
        }
        
    except Exception as e:
        structured_logger.log_error(
            error_type="job_search_failed",
            component="search_jobs_task",
            message=str(e),
            exception=e,
            user_id=user_id
        )
        raise


@retry(max_attempts=3)
@timeout(60.0)
async def _search_jobs_async(
    query: str,
    location: str,
    remote: bool,
    limit: int,
    user_id: str
) -> List[Dict]:
    """Async job search with retry and timeout"""
    from services.scraper.linkedin import LinkedInScraper
    from services.scraper.indeed import IndeedScraper
    
    jobs = []
    
    # Search LinkedIn
    try:
        linkedin = LinkedInScraper()
        await linkedin.initialize()
        linkedin_jobs = await linkedin.search_jobs(query, location or "Remote", max_results=limit//2)
        jobs.extend(linkedin_jobs)
    except Exception as e:
        structured_logger.log_error(
            error_type="linkedin_scrape_failed",
            component="job_search",
            message=str(e),
            exception=e
        )

    # Search Indeed
    try:
        indeed = IndeedScraper()
        await indeed.initialize()
        indeed_jobs = await indeed.search_jobs(query, location or "Remote", max_results=limit//2)
        jobs.extend(indeed_jobs)
    except Exception as e:
        structured_logger.log_error(
            error_type="indeed_scrape_failed",
            component="job_search",
            message=str(e),
            exception=e
        )
    
    # Score jobs using AI
    scored_jobs = await _score_jobs_with_ai(jobs, user_id)
    
    return scored_jobs


async def _score_jobs_with_ai(jobs: List[Dict], user_id: str) -> List[Dict]:
    """Score jobs using AI model with caching"""
    from config.user_profile import get_user_profile
    
    user_profile = get_user_profile(user_id)
    user_skills = user_profile.get("skills", [])
    
    for job in jobs:
        # Generate scoring prompt
        prompt = f"""
        Score this job match from 0-100 based on user skills.
        
        Job: {job['title']} at {job['company']}
        Description: {job.get('description', '')[:500]}
        
        User skills: {', '.join(user_skills)}
        
        Return only a number 0-100.
        """
        
        # Use AI with caching
        result = await model_router.complete(
            prompt=prompt,
            model="llama-3-70b",
            temperature=0.3,
            max_tokens=10,
            use_cache=True
        )
        
        # Parse score
        try:
            score = int(result["response"].strip())
            job["match_score"] = min(100, max(0, score))
        except:
            job["match_score"] = 50  # Default score
    
    # Sort by score
    jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    
    return jobs


@celery_app.task(
    base=BaseTask,
    bind=True,
    name="workers.job_search.run_daily_search"
)
def run_daily_search(self):
    """
    Daily automated job search for all users
    Scheduled by Celery Beat
    """
    from models.database import SessionLocal as Session, User

    db = Session()

    try:
        # Get all active users
        users = db.query(User).filter(User.is_active == True).all()
        
        for user in users:
            # Get user's search preferences
            for search_query in user.target_roles:
                # Submit search task
                search_jobs_task.delay(
                    query=search_query,
                    location=user.location,
                    remote=user.remote_preference,
                    limit=100,
                    user_id=user.id
                )
        
        return {
            "status": "success",
            "users_processed": len(users)
        }
        
    finally:
        db.close()


# ==================== RESUME GENERATION WORKER ====================

@celery_app.task(
    base=BaseTask,
    bind=True,
    name="workers.resume_generation.generate_resume_task"
)
def generate_resume_task(
    self,
    job_id: str,
    variant: str = "balanced",
    user_id: Optional[str] = None,
    custom_skills: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate ATS-optimized resume with quality evaluation
    """
    start_time = datetime.now(timezone.utc)
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        result = loop.run_until_complete(
            _generate_resume_async(job_id, variant, user_id, custom_skills)
        )
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Log metrics
        from infrastructure.monitoring import (
            resumes_generated_total,
            resume_generation_duration,
            resume_ats_score
        )
        
        resumes_generated_total.labels(
            variant=variant,
            status="success"
        ).inc()
        
        resume_generation_duration.labels(variant=variant).observe(duration)
        resume_ats_score.labels(variant=variant).observe(result["ats_score"])
        
        return result
        
    except Exception as e:
        structured_logger.log_error(
            error_type="resume_generation_failed",
            component="generate_resume_task",
            message=str(e),
            exception=e,
            user_id=user_id
        )
        raise


@retry(max_attempts=2)
@timeout(120.0)
async def _generate_resume_async(
    job_id: str,
    variant: str,
    user_id: str,
    custom_skills: List[str]
) -> Dict[str, Any]:
    """Generate resume with AI"""
    from models.database import SessionLocal as Session, Job
    from config.user_profile import get_user_profile
    from services.resume.ats_optimizer import ATSResumeEngine as ATSOptimizer
    
    db = Session()
    
    try:
        # Get job details
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Get user profile
        user_profile = get_user_profile(user_id)
        
        # Generate resume using AI
        prompt = f"""
        Generate an ATS-optimized resume for this job.
        
        Job Title: {job.title}
        Company: {job.company}
        Description: {job.description}
        
        User Profile:
        Name: {user_profile['name']}
        Skills: {', '.join(user_profile.get('skills', []))}
        Experience: {user_profile.get('experience', [])}
        
        Variant: {variant}
        
        Return resume in plain text format optimized for ATS.
        """
        
        # Use AI to generate
        result = await model_router.complete(
            prompt=prompt,
            model="gpt-4",  # Use better model for resumes
            temperature=0.7,
            max_tokens=2000,
            use_cache=False  # Don't cache resumes
        )
        
        resume_text = result["response"]
        
        # Evaluate quality
        metrics = quality_evaluator.evaluate_resume(
            resume_text=resume_text,
            job_description=job.description
        )
        
        # Save to database
        from models.database import Resume
        
        resume = Resume(
            user_id=user_id,
            job_id=job_id,
            variant=variant,
            content=resume_text,
            ats_score=(metrics.ats_score or 0) * 100,
            keyword_match=(metrics.keyword_match or 0) * 100
        )

        db.add(resume)
        db.commit()

        return {
            "status": "success",
            "resume_id": resume.id,
            "ats_score": (metrics.ats_score or 0) * 100,
            "keyword_match": (metrics.keyword_match or 0) * 100,
            "overall_quality": (metrics.overall_score or 0) * 100,
            "llm_cost": result["cost_usd"]
        }
        
    finally:
        db.close()


# ==================== APPLICATION SUBMISSION WORKER ====================

@celery_app.task(
    base=BaseTask,
    bind=True,
    name="workers.application_submission.submit_application_task"
)
@idempotent(operation_name="job_application", ttl=86400*7)
def submit_application_task(
    self,
    job_id: str,
    resume_id: str,
    cover_letter_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Submit job application with browser automation
    Idempotent to prevent duplicate submissions
    """
    start_time = datetime.now(timezone.utc)
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        result = loop.run_until_complete(
            _submit_application_async(job_id, resume_id, cover_letter_id, user_id)
        )
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Log metrics
        from infrastructure.monitoring import (
            applications_submitted_total,
            application_submission_duration
        )
        
        applications_submitted_total.labels(
            platform=result["platform"],
            status="success"
        ).inc()
        
        application_submission_duration.labels(
            platform=result["platform"]
        ).observe(duration)
        
        return result
        
    except Exception as e:
        structured_logger.log_error(
            error_type="application_submission_failed",
            component="submit_application_task",
            message=str(e),
            exception=e,
            user_id=user_id
        )
        raise


@retry(max_attempts=2)
@timeout(300.0)  # 5 minutes for browser automation
async def _submit_application_async(
    job_id: str,
    resume_id: str,
    cover_letter_id: str,
    user_id: str
) -> Dict[str, Any]:
    """Submit application using browser automation"""
    from models.database import SessionLocal as Session, Job, Resume, Application
    from services.automation.form_filler import FormFillingEngine as FormFiller
    
    db = Session()
    
    try:
        # Get job and resume
        job = db.query(Job).filter(Job.id == job_id).first()
        resume = db.query(Resume).filter(Resume.id == resume_id).first()
        
        if not job or not resume:
            raise ValueError("Job or resume not found")
        
        # Use browser automation
        filler = FormFiller()
        
        submission_result = await filler.submit_application(
            job_url=job.url,
            resume_path=resume.file_path,
            user_id=user_id
        )
        
        # Save application record
        application = Application(
            user_id=user_id,
            job_id=job_id,
            resume_id=resume_id,
            status="submitted",
            submitted_at=datetime.now(timezone.utc),
            platform=job.platform
        )
        
        db.add(application)
        db.commit()
        
        # Log the submission
        structured_logger.log_application_submission(
            platform=job.platform,
            job_id=job_id,
            status="success",
            duration=0.0,
            user_id=user_id
        )
        
        return {
            "status": "success",
            "application_id": application.id,
            "platform": job.platform,
            "job_title": job.title,
            "company": job.company
        }
        
    finally:
        db.close()


# ==================== MONITORING WORKER ====================

@celery_app.task(
    base=BaseTask,
    bind=True,
    name="workers.monitoring.generate_metrics"
)
def generate_metrics(self):
    """
    Generate system metrics periodically
    Scheduled by Celery Beat every 15 minutes
    """
    from infrastructure.monitoring import (
        active_users, db_connections_active,
        llm_cache_hit_rate, cache_hit_rate
    )
    from infrastructure.cache import CacheMetrics
    from models.database import SessionLocal as Session, User

    db = Session()

    try:
        # Active users (logged in within last hour)
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        active_count = db.query(User).filter(
            User.last_login > cutoff
        ).count()
        
        active_users.set(active_count)
        
        # Database connections
        # db_connections_active.set(db.bind.pool.checkedout())
        
        # Cache hit rates
        llm_hit_rate = CacheMetrics.get_hit_rate("llm")
        llm_cache_hit_rate.labels(model="all").set(llm_hit_rate)
        
        cache_hit_rate.labels(cache_type="all").set(
            CacheMetrics.get_hit_rate("all")
        )
        
        return {
            "status": "success",
            "active_users": active_count,
            "llm_cache_hit_rate": llm_hit_rate
        }
        
    finally:
        db.close()


@celery_app.task(
    base=BaseTask,
    bind=True,
    name="workers.monitoring.cleanup_old_data"
)
def cleanup_old_data(self):
    """
    Cleanup old data from database
    Scheduled by Celery Beat at 2 AM daily
    """
    from models.database import SessionLocal as Session, Job
    from datetime import timedelta

    db = Session()

    try:
        # Delete jobs older than 30 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        
        deleted_count = db.query(Job).filter(
            Job.scraped_at < cutoff
        ).delete()
        
        db.commit()
        
        structured_logger.log_error(
            error_type="cleanup",
            component="cleanup_old_data",
            message=f"Deleted {deleted_count} old jobs"
        )
        
        return {
            "status": "success",
            "deleted_jobs": deleted_count
        }
        
    finally:
        db.close()
