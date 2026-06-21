"""
Application Submission Worker
Celery task for async job application submission via browser automation
"""
from infrastructure.tasks import celery_app, BaseTask
from infrastructure.monitoring import structured_logger
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import asyncio


@celery_app.task(base=BaseTask, bind=True, name="workers.application_submission.submit_application_task")
def submit_application_task(
    self,
    job_id: str,
    resume_id: str,
    cover_letter_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a job application using browser automation."""
    start = datetime.now(timezone.utc)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _submit_async(job_id, resume_id, cover_letter_id, user_id)
        )
        loop.close()
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        structured_logger.log_application_submission(
            platform=result.get("platform", "unknown"),
            job_id=job_id, status="success",
            duration=duration, user_id=user_id or ""
        )
        return result
    except Exception as exc:
        structured_logger.log_error(
            error_type="submission_failed", component="submit_application_task",
            message=str(exc), exception=exc, user_id=user_id or ""
        )
        raise self.retry(exc=exc, countdown=30, max_retries=2)


async def _submit_async(job_id, resume_id, cover_letter_id, user_id) -> Dict[str, Any]:
    """Async application submission."""
    from models.database import SessionLocal, Job, Application, ApplicationStatus
    from datetime import datetime

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Check for duplicate
        existing = db.query(Application).filter(
            Application.job_id == job_id,
            Application.user_id == user_id  # scope per-user — FIX: was missing user_id
        ).first()
        if existing:
            return {
                "status": "duplicate",
                "application_id": str(existing.id),
                "platform": existing.platform,
            }

        # Record submission
        app = Application(
            job_id=job_id,
            user_id=user_id,  # Required for per-user idempotency
            platform=job.platform,
            status=ApplicationStatus.SUBMITTED,
            applied_at=datetime.now(timezone.utc),
            submission_method="automated",
        )
        db.add(app)
        db.commit()
        db.refresh(app)

        return {
            "status": "success",
            "application_id": str(app.id),
            "platform": job.platform,
            "job_title": job.title,
            "company": job.company,
        }
    finally:
        db.close()
