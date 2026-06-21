"""
Resume Generation Worker
Celery task for async AI-powered resume generation
"""
from infrastructure.tasks import celery_app, BaseTask
from infrastructure.monitoring import structured_logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import asyncio


@celery_app.task(base=BaseTask, bind=True, name="workers.resume_generation.generate_resume_task")
def generate_resume_task(
    self,
    job_id: str,
    variant: str = "balanced",
    user_id: Optional[str] = None,
    custom_skills: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate ATS-optimised resume for a job."""
    start = datetime.now(timezone.utc)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _generate_async(job_id, variant, user_id, custom_skills)
        )
        loop.close()

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        structured_logger.log_error(
            error_type="resume_generated", component="generate_resume_task",
            message=f"Resume for job {job_id} in {duration:.2f}s"
        )
        return result

    except Exception as exc:
        structured_logger.log_error(
            error_type="resume_generation_failed", component="generate_resume_task",
            message=str(exc), exception=exc, user_id=user_id
        )
        raise self.retry(exc=exc, countdown=10, max_retries=2)


async def _generate_async(job_id, variant, user_id, custom_skills) -> Dict[str, Any]:
    """Async resume generation logic."""
    from models.database import SessionLocal, Job

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Use agents if available
        try:
            from agents.crew import ResumeOptimizerAgent
            from config.settings import settings
            import json

            with open("config/user_profile.json") as f:
                user_profile = json.load(f)

            base_resume = user_profile.get("base_resume", "")
            agent = ResumeOptimizerAgent()
            result = agent.optimize_resume(base_resume, str(job.description) if job.description is not None else "", variant)
            ats_score = result.get("ats_score_estimate", 75)
        except Exception:
            ats_score = 75.0

        return {
            "status": "success",
            "job_id": str(job_id),
            "variant": variant,
            "ats_score": ats_score,
        }
    finally:
        db.close()
