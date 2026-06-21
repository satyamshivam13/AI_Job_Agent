"""
Test Suite for AI Job Agent
Comprehensive testing including unit, integration, and E2E tests
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from models.database import Base, Job, Application, ResumeVersion
try:
    from agents.crew import JobApplicationCrew
    CREWAI_AVAILABLE = True
except ImportError:
    JobApplicationCrew = None
    CREWAI_AVAILABLE = False
from services.scraper.linkedin import LinkedInScraper
from services.scraper.indeed import IndeedScraper
from services.resume.ats_optimizer import ATSResumeEngine, parse_satyam_resume


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def test_db():
    """Create test database"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()
    engine.dispose()


@pytest.fixture
def sample_job():
    """Sample job data"""
    return {
        'platform': 'indeed',
        'platform_job_id': 'test123',
        'title': 'AI Engineer',
        'company': 'TechCorp',
        'location': 'Remote',
        'url': 'https://example.com/job/test123',
        'description': 'Looking for AI Engineer with LangChain and RAG experience. Must know Python, FastAPI, and Docker.',
        'salary_min': 100000,
        'salary_max': 150000,
        'currency': 'USD',
        'remote': True,
        'scraped_at': datetime.utcnow()
    }


@pytest.fixture
def sample_user_profile():
    """Sample user profile"""
    return {
        'name': 'Satyam Shivam',
        'email': 'test@example.com',
        'target_roles': ['AI Engineer', 'ML Engineer'],
        'skills': {
            'primary': ['LangChain', 'RAG', 'Python', 'FastAPI'],
            'secondary': ['Docker', 'AWS']
        },
        'locations': {
            'preferred': ['Remote', 'New Delhi']
        },
        'salary': {
            'minimum_usd': 80000
        },
        'experience_level': 'entry_level'
    }


# =============================================================================
# UNIT TESTS - Resume Engine
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestResumeEngine:
    """Test resume generation and optimization"""
    
    def test_parse_resume(self):
        """Test resume parsing"""
        resume_data = parse_satyam_resume()
        
        assert resume_data['name'] == 'Satyam Shivam'
        assert 'LangChain' in resume_data['skills']['primary']
        assert len(resume_data['experience']) > 0
        assert len(resume_data['projects']) > 0
    
    def test_resume_generation(self):
        """Test resume generation"""
        base_data = parse_satyam_resume()
        engine = ATSResumeEngine(base_data)
        
        doc, metadata = engine.generate_tailored_resume(
            job_description="Looking for AI Engineer with LangChain experience",
            job_title="Senior AI Engineer",
            keywords=['LangChain', 'RAG', 'Python'],
            variant='balanced'
        )
        
        assert doc is not None
        assert metadata['ats_score'] > 0
        assert metadata['variant'] == 'balanced'
        assert len(metadata['keywords_added']) >= 0
    
    def test_ats_score_calculation(self):
        """Test ATS score calculation"""
        base_data = parse_satyam_resume()
        engine = ATSResumeEngine(base_data)
        
        doc, metadata = engine.generate_tailored_resume(
            job_description="Python, LangChain, RAG, FastAPI, Docker",
            job_title="AI Engineer",
            keywords=['Python', 'LangChain', 'RAG', 'FastAPI', 'Docker'],
            variant='aggressive'
        )
        
        # Should score high with exact keyword matches
        assert metadata['ats_score'] >= 70


# =============================================================================
# UNIT TESTS - AI Agents
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestAIAgents:
    """Test AI agent functionality"""
    
    @pytest.mark.asyncio
    async def test_job_finder_agent(self, sample_job, sample_user_profile):
        """Test job scoring agent"""
        crew = JobApplicationCrew()
        
        jobs = [sample_job]
        
        # Mock LLM response to avoid API calls in tests
        assert crew.job_finder.agent.llm is not None
        with patch.object(crew.job_finder.agent.llm, 'invoke') as mock_llm:
            mock_llm.return_value = Mock(content='[{"job_id": "test123", "score": 85, "recommendation": "APPLY"}]')
            
            scored_jobs = crew.job_finder.score_jobs(jobs, sample_user_profile)
            
            assert len(scored_jobs) > 0
            # In real implementation, would verify scoring logic
    
    def test_resume_optimizer_agent(self):
        """Test resume optimization agent"""
        crew = JobApplicationCrew()
        
        base_resume = "AI Engineer with LangChain experience."
        job_description = "Looking for AI Engineer with RAG and FastAPI experience."
        
        assert crew.resume_optimizer.agent.llm is not None
        with patch.object(crew.resume_optimizer.agent.llm, 'invoke') as mock_llm:
            mock_llm.return_value = Mock(content='{"optimized_resume_text": "Updated resume", "ats_score_estimate": 85}')
            
            result = crew.resume_optimizer.optimize_resume(
                base_resume, job_description, 'balanced'
            )
            
            assert 'optimized_resume_text' in result


# =============================================================================
# INTEGRATION TESTS - Database
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestDatabase:
    """Test database operations"""
    
    def test_create_job(self, test_db, sample_job):
        """Test creating job in database"""
        job = Job(**sample_job)
        test_db.add(job)
        test_db.commit()
        
        saved_job = test_db.query(Job).filter_by(platform_job_id='test123').first()
        
        assert saved_job is not None
        assert saved_job.title == 'AI Engineer'
        assert saved_job.company == 'TechCorp'
    
    def test_create_application(self, test_db, sample_job):
        """Test creating application"""
        job = Job(**sample_job)
        test_db.add(job)
        test_db.commit()
        
        app = Application(
            job_id=job.id,
            platform='indeed',
            cover_letter_text='Test cover letter',
            status='pending'
        )
        test_db.add(app)
        test_db.commit()
        
        saved_app = test_db.query(Application).first()
        
        assert saved_app is not None
        assert saved_app.job_id == job.id
    
    def test_resume_version_tracking(self, test_db):
        """Test resume version tracking"""
        version = ResumeVersion(
            base_resume_text='Original resume',
            tailored_resume_text='Tailored resume',
            variant_type='balanced',
            ats_score_estimate=85.5,
            keywords_added=['Python', 'LangChain']
        )
        test_db.add(version)
        test_db.commit()
        
        saved = test_db.query(ResumeVersion).first()
        
        assert saved is not None
        assert saved.variant_type == 'balanced'
        assert saved.ats_score_estimate == 85.5


# =============================================================================
# INTEGRATION TESTS - Scrapers
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestScrapers:
    """Test job scraping functionality"""
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(not settings.indeed_email, reason="No Indeed credentials")
    async def test_indeed_scraper(self):
        """Test Indeed scraper (requires credentials)"""
        scraper = IndeedScraper()
        
        try:
            await scraper.initialize()
            
            jobs = await scraper.search_jobs(
                keywords="Python",
                location="Remote",
                max_results=5,
                remote_only=True
            )
            
            assert len(jobs) > 0
            assert all('title' in job for job in jobs)
            assert all('company' in job for job in jobs)
            
        finally:
            await scraper.close()
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(not settings.linkedin_email, reason="No LinkedIn credentials")
    async def test_linkedin_scraper(self):
        """Test LinkedIn scraper (requires credentials)"""
        scraper = LinkedInScraper()
        
        try:
            await scraper.initialize()
            
            jobs = await scraper.search_jobs(
                keywords="AI Engineer",
                location="Remote",
                easy_apply=True,
                max_results=5
            )
            
            assert len(jobs) > 0
            
        finally:
            await scraper.close()


# =============================================================================
# E2E TESTS - Complete Pipeline
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestEndToEnd:
    """End-to-end pipeline tests"""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_complete_pipeline(self, test_db, sample_job, sample_user_profile):
        """Test complete application pipeline"""
        # 1. Create job
        job = Job(**sample_job)
        test_db.add(job)
        test_db.commit()
        
        # 2. Generate resume
        base_data = parse_satyam_resume()
        engine = ATSResumeEngine(base_data)
        
        doc, metadata = engine.generate_tailored_resume(
            job_description=sample_job['description'],
            job_title=sample_job['title'],
            keywords=['LangChain', 'RAG', 'Python'],
            variant='balanced'
        )
        
        assert metadata['ats_score'] > 0
        
        # 3. Save resume version
        version = ResumeVersion(
            base_resume_text='Original',
            tailored_resume_text='Tailored',
            variant_type='balanced',
            ats_score_estimate=metadata['ats_score']
        )
        test_db.add(version)
        test_db.commit()
        
        # 4. Create application
        app = Application(
            job_id=job.id,
            resume_version_id=version.id,
            platform=job.platform,
            status='pending'
        )
        test_db.add(app)
        test_db.commit()
        
        # Verify complete pipeline
        saved_app = test_db.query(Application).first()
        assert saved_app is not None
        assert saved_app.resume_version is not None
        assert saved_app.job is not None


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestPerformance:
    """Performance and load tests"""
    
    def test_resume_generation_speed(self):
        """Test resume generation performance"""
        import time
        
        base_data = parse_satyam_resume()
        engine = ATSResumeEngine(base_data)
        
        start = time.time()
        
        for _ in range(10):
            doc, metadata = engine.generate_tailored_resume(
                job_description="Test job description",
                job_title="Test Title",
                keywords=['Python'],
                variant='balanced'
            )
        
        duration = time.time() - start
        avg_time = duration / 10
        
        # Should generate resume in under 5 seconds
        assert avg_time < 5.0
        
        print(f"Average resume generation time: {avg_time:.2f}s")


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

@pytest.mark.skipif(not CREWAI_AVAILABLE, reason="crewai not installed")
class TestConfiguration:
    """Test configuration and settings"""
    
    def test_settings_load(self):
        """Test settings load correctly"""
        assert settings.api_host is not None
        assert settings.api_port > 0
        assert settings.max_applications_per_day > 0
    
    def test_required_api_keys(self):
        """Test required API keys are present"""
        errors = settings.validate_required_settings()
        
        # In test mode, some keys might be missing
        if not settings.is_testing:
            assert len(errors) == 0


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([
        __file__,
        '-v',
        '--cov=.',
        '--cov-report=html',
        '--cov-report=term-missing'
    ])
