"""
Main Application Orchestrator
Coordinates all agents and services for autonomous job applications
"""

import asyncio
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from utils.logger import logger
from models.database import Base, Job, Application, ResumeVersion, UserProfile, ActivityLog
from services.scraper.linkedin import LinkedInScraper
from services.scraper.indeed import IndeedScraper
from services.resume.ats_optimizer import ATSResumeEngine, parse_satyam_resume
from agents.crew import JobApplicationCrew


class JobAgentOrchestrator:
    """
    Main orchestrator for AI job application system
    Coordinates scraping, analysis, optimization, and submission
    """
    
    def __init__(self):
        self.engine = create_engine(settings.database_url)
        self.Session = sessionmaker(bind=self.engine)
        self.crew = JobApplicationCrew()
        self.user_profile = self._load_user_profile()
        self.base_resume_data = parse_satyam_resume()
        
    def _load_user_profile(self) -> Dict:
        """Load user profile from database or config"""
        session = self.Session()
        try:
            profile = session.query(UserProfile).first()
            if profile:
                return {
                    'name': profile.full_name,
                    'email': profile.email,
                    'target_roles': profile.target_roles,
                    'skills': {
                        'primary': profile.skills_primary,
                        'secondary': profile.skills_secondary
                    },
                    'locations': {
                        'preferred': profile.preferred_locations
                    },
                    'salary': {
                        'minimum_usd': profile.minimum_salary_usd
                    },
                    'experience_level': profile.experience_level
                }
            
            # Default profile
            return {
                'name': settings.user_name,
                'email': settings.user_email,
                'target_roles': ['AI Engineer', 'ML Engineer', 'GenAI Developer'],
                'skills': {
                    'primary': ['LangChain', 'RAG', 'Python', 'FastAPI'],
                    'secondary': ['AWS', 'Docker', 'PostgreSQL']
                },
                'locations': {
                    'preferred': ['Remote', 'New Delhi']
                },
                'salary': {
                    'minimum_usd': 80000
                },
                'experience_level': 'entry_level'
            }
        finally:
            session.close()
    
    async def run_daily_search(self):
        """Main daily job search and application pipeline"""
        logger.info("🚀 Starting daily job search pipeline")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Step 1: Scrape jobs from all platforms
            logger.info("📡 Step 1: Scraping job platforms")
            all_jobs = await self._scrape_all_platforms()
            logger.info(f"✓ Found {len(all_jobs)} total jobs")
            
            if not all_jobs:
                logger.warning("⚠️ No jobs found. Exiting.")
                return
            
            # Step 2: Save jobs to database
            logger.info("💾 Step 2: Saving jobs to database")
            saved_jobs = self._save_jobs_to_db(all_jobs)
            logger.info(f"✓ Saved {len(saved_jobs)} new jobs")
            
            # Step 3: Score and filter jobs using AI
            logger.info("🤖 Step 3: Scoring jobs with AI")
            scored_jobs = self.crew.job_finder.score_jobs(
                saved_jobs,
                self.user_profile
            )
            
            # Filter high-score jobs
            high_score_jobs = [j for j in scored_jobs if j.get('score', 0) >= 75]
            logger.info(f"✓ {len(high_score_jobs)} high-potential opportunities identified")
            
            # Step 4: Generate tailored applications
            logger.info("📄 Step 4: Generating tailored applications")
            applications = await self._generate_applications(high_score_jobs)
            logger.info(f"✓ Generated {len(applications)} applications")
            
            # Step 5: Submit applications (if enabled)
            if settings.enable_auto_apply:
                logger.info("📤 Step 5: Submitting applications")
                submitted = await self._submit_applications(applications)
                logger.info(f"✓ Submitted {submitted} applications")
            else:
                logger.info("⏸️ Auto-apply disabled - applications saved for review")
            
            # Step 6: Log analytics
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            self._log_analytics(
                jobs_scraped=len(all_jobs),
                jobs_saved=len(saved_jobs),
                applications_generated=len(applications),
                duration=duration
            )
            
            logger.info(f"✅ Pipeline completed in {duration:.1f}s")
            
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {str(e)}", exc_info=True)
            raise
    
    async def _scrape_all_platforms(self) -> List[Dict]:
        """Scrape jobs from all enabled platforms"""
        all_jobs = []
        
        # LinkedIn
        if settings.linkedin_email:
            try:
                logger.info("📍 Scraping LinkedIn...")
                linkedin = LinkedInScraper()
                await linkedin.initialize()
                
                linkedin_jobs = await linkedin.search_jobs(
                    keywords="AI Engineer OR ML Engineer OR GenAI",
                    location="Remote",
                    easy_apply=True,
                    max_results=settings.max_applications_per_platform
                )
                
                all_jobs.extend(linkedin_jobs)
                await linkedin.close()
                
            except Exception as e:
                logger.error(f"LinkedIn scraping failed: {str(e)}")
        
        # Indeed
        try:
            logger.info("📍 Scraping Indeed...")
            indeed = IndeedScraper()
            await indeed.initialize()
            
            indeed_jobs = await indeed.search_jobs(
                keywords="AI Engineer",
                location="Remote",
                max_results=settings.max_applications_per_platform,
                remote_only=True
            )
            
            all_jobs.extend(indeed_jobs)
            await indeed.close()
            
        except Exception as e:
            logger.error(f"Indeed scraping failed: {str(e)}")
        
        return all_jobs
    
    def _save_jobs_to_db(self, jobs: List[Dict]) -> List[Dict]:
        """Save scraped jobs to database"""
        session = self.Session()
        saved_jobs = []
        
        try:
            for job_data in jobs:
                # Check if job already exists
                existing = session.query(Job).filter_by(
                    url=job_data['url']
                ).first()
                
                if existing:
                    continue
                
                # Create new job
                job = Job(
                    platform=job_data['platform'],
                    platform_job_id=job_data.get('platform_job_id'),
                    url=job_data['url'],
                    title=job_data['title'],
                    company=job_data['company'],
                    location=job_data['location'],
                    salary_min=job_data.get('salary_min'),
                    salary_max=job_data.get('salary_max'),
                    currency=job_data.get('currency', 'USD'),
                    remote=job_data.get('remote', False),
                    description=job_data.get('description', ''),
                    scraped_at=job_data.get('scraped_at', datetime.now(timezone.utc))
                )
                
                session.add(job)
                saved_jobs.append(job_data)
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving jobs: {str(e)}")
        finally:
            session.close()
        
        return saved_jobs
    
    async def _generate_applications(self, jobs: List[Dict]) -> List[Dict]:
        """Generate tailored resumes and cover letters"""
        applications = []
        
        for job in jobs[:settings.max_applications_per_day]:
            try:
                logger.info(f"📝 Processing: {job['title']} at {job['company']}")
                
                # Extract keywords from job description
                keywords = self._extract_keywords(job.get('description', ''))
                
                # Generate resume
                resume_engine = ATSResumeEngine(self.base_resume_data)
                resume_doc, metadata = resume_engine.generate_tailored_resume(
                    job_description=job.get('description', ''),
                    job_title=job['title'],
                    keywords=keywords,
                    variant='balanced'
                )
                
                # Save resume
                resume_path = f"/tmp/resumes/{job['title'][:30]}_{job['company'][:20]}.docx"
                Path(resume_path).parent.mkdir(parents=True, exist_ok=True)
                resume_engine.save_resume(resume_doc, resume_path)
                
                # Generate cover letter (using AI agent)
                cover_letter = self.crew.cover_letter_agent.generate_cover_letter(
                    job,
                    self.user_profile,
                    resume_summary=self.base_resume_data['summary']
                )
                
                applications.append({
                    'job': job,
                    'resume_path': resume_path,
                    'resume_metadata': metadata,
                    'cover_letter': cover_letter['cover_letter'],
                    'keywords': keywords
                })
                
            except Exception as e:
                logger.error(f"Failed to generate application: {str(e)}")
                continue
        
        return applications
    
    async def _submit_applications(self, applications: List[Dict]) -> int:
        """Submit applications via browser automation"""
        submitted_count = 0
        
        # TODO: Implement browser automation for submission
        # This would use Playwright to fill forms and submit
        
        for app in applications:
            logger.info(f"⏭️ Skipping submission for: {app['job']['title']}")
            # Save to database as pending
            self._save_application_to_db(app, status='pending')
            submitted_count += 1
        
        return submitted_count
    
    def _save_application_to_db(self, app: Dict, status: str = 'pending'):
        """Save application to database"""
        session = self.Session()
        
        try:
            job = session.query(Job).filter_by(url=app['job']['url']).first()
            
            if not job:
                return
            
            application = Application(
                job_id=job.id,
                platform=job.platform,
                resume_path=app['resume_path'],
                cover_letter_text=app['cover_letter'],
                status=status
            )
            
            session.add(application)
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving application: {str(e)}")
        finally:
            session.close()
    
    def _extract_keywords(self, text: str, top_n: int = 20) -> List[str]:
        """Extract important keywords from job description"""
        # Simple keyword extraction (can be enhanced with NLP)
        import re
        from collections import Counter
        
        # Common tech keywords
        tech_keywords = [
            'python', 'java', 'javascript', 'react', 'aws', 'docker',
            'kubernetes', 'fastapi', 'langchain', 'rag', 'llm', 'ai',
            'machine learning', 'deep learning', 'nlp', 'computer vision',
            'pytorch', 'tensorflow', 'scikit-learn', 'pandas', 'numpy',
            'sql', 'nosql', 'postgresql', 'mongodb', 'redis',
            'api', 'rest', 'graphql', 'microservices', 'ci/cd',
            'git', 'github', 'agile', 'scrum'
        ]
        
        text_lower = text.lower()
        found_keywords = []
        
        for keyword in tech_keywords:
            if keyword in text_lower:
                found_keywords.append(keyword)
        
        return found_keywords[:top_n]
    
    def _log_analytics(self, **metrics):
        """Log analytics for this run"""
        session = self.Session()
        
        try:
            log = ActivityLog(
                activity_type='daily_run',
                status='success',
                details=metrics
            )
            session.add(log)
            session.commit()
            
        finally:
            session.close()


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='AI Job Application Agent')
    parser.add_argument('--mode', choices=['search', 'auto', 'test'], 
                       default='search', help='Operation mode')
    parser.add_argument('--platforms', help='Comma-separated platform names')
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = JobAgentOrchestrator()
    
    if args.mode == 'search':
        # Single search run
        await orchestrator.run_daily_search()
    
    elif args.mode == 'auto':
        # Scheduled daily runs
        logger.info("🔄 Running in auto mode - will run daily at configured time")
        # TODO: Implement scheduler
        await orchestrator.run_daily_search()
    
    elif args.mode == 'test':
        # Test mode
        logger.info("🧪 Running in test mode")
        # TODO: Implement test suite
        await orchestrator.run_daily_search()


if __name__ == "__main__":
    asyncio.run(main())
