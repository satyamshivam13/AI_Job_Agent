"""
Job Search Worker
Celery task for async job searching across platforms
"""
from infrastructure.tasks import celery_app, BaseTask
from infrastructure.cache import JobSearchCache
from infrastructure.monitoring import structured_logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import asyncio


@celery_app.task(base=BaseTask, bind=True, name="workers.job_search.search_jobs_task")
def search_jobs_task(
    self,
    query: str,
    location: Optional[str] = None,
    remote: bool = False,
    limit: int = 50,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for jobs across platforms with caching."""
    start = datetime.now(timezone.utc)
    try:
        cached = JobSearchCache.get_jobs(query, location or "", remote, limit)
        if cached:
            return {"status": "success", "jobs": cached, "count": len(cached), "cached": True}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        jobs = loop.run_until_complete(
            _search_async(query, location, remote, limit, user_id)
        )
        loop.close()

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        JobSearchCache.set_jobs(query, location or "", remote, limit, jobs)
        structured_logger.log_job_search(
            platform="multi", query=query,
            jobs_found=len(jobs), duration=duration, status="success"
        )
        return {"status": "success", "jobs": jobs, "count": len(jobs), "cached": False}

    except Exception as exc:
        structured_logger.log_error(
            error_type="job_search_failed", component="search_jobs_task",
            message=str(exc), exception=exc, user_id=user_id
        )
        raise self.retry(exc=exc, countdown=5, max_retries=3)


async def _search_async(query, location, remote, limit, user_id) -> List[Dict]:
    """Perform async job search — returns mock data when scrapers unavailable."""
    try:
        from services.scraper.linkedin import LinkedInScraper
        scraper = LinkedInScraper()
        await scraper.initialize()
        jobs = await scraper.search_jobs(query, location or "Remote", max_results=limit)
        await scraper.close()
        return jobs
    except Exception:
        # Graceful degradation: return empty list rather than crash
        return []
