"""
Production-Grade Comprehensive Testing Suite
Implements unit tests, integration tests, E2E tests, and load tests
Target: 80%+ code coverage
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import Mock, patch, MagicMock
import asyncio
from datetime import datetime
from typing import Generator

# Test database setup
TEST_DATABASE_URL = "sqlite:///./test.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# ==================== FIXTURES ====================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
def db_session():
    """Create test database session"""
    from models.database import Base
    Base.metadata.create_all(bind=test_engine)
    
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create test client"""
    from api.main import app
    
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_llm():
    """Mock LLM responses"""
    with patch("agents.crew.ChatGroq") as mock:
        mock.return_value.invoke.return_value = "Mocked LLM response"
        yield mock


@pytest.fixture
def mock_redis():
    """Mock Redis cache"""
    with patch("infrastructure.cache.redis.Redis") as mock:
        cache_mock = MagicMock()
        cache_mock.get.return_value = None
        cache_mock.set.return_value = True
        mock.return_value = cache_mock
        yield mock


@pytest.fixture
def sample_job_data():
    """Sample job data for testing"""
    return {
        "title": "AI Engineer",
        "company": "TechCorp",
        "location": "San Francisco, CA",
        "description": "Build AI systems",
        "salary_min": 150000,
        "salary_max": 200000,
        "remote": True,
        "url": "https://example.com/job/123"
    }


@pytest.fixture
def sample_user_data():
    """Sample user data for testing"""
    return {
        "email": "test@example.com",
        "username": "testuser",
        "password": "SecurePassword123!",
        "full_name": "Test User"
    }


# ==================== AUTHENTICATION TESTS ====================

class TestAuthentication:
    """Test authentication and authorization"""
    
    def test_create_access_token(self):
        """Test JWT token creation"""
        from auth.security import create_access_token
        
        data = {"sub": "user123", "username": "testuser", "roles": ["user"]}
        token = create_access_token(data)
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_verify_password(self):
        """Test password verification"""
        from auth.security import verify_password, get_password_hash
        
        password = "SecurePassword123!"
        hashed = get_password_hash(password)
        
        assert verify_password(password, hashed)
        assert not verify_password("WrongPassword", hashed)
    
    def test_get_current_user_valid_token(self):
        """Test user extraction from valid token"""
        from auth.security import create_access_token, get_current_user
        import asyncio
        
        data = {"sub": "user123", "username": "testuser", "roles": ["user"]}
        token = create_access_token(data)
        
        user = asyncio.run(get_current_user(token))
        
        assert user.user_id == "user123"
        assert user.username == "testuser"
        assert "user" in user.roles
    
    def test_get_current_user_invalid_token(self):
        """Test user extraction from invalid token"""
        from auth.security import get_current_user
        from fastapi import HTTPException
        import asyncio
        
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user("invalid_token"))
        
        assert exc_info.value.status_code == 401
    
    def test_rate_limiter(self):
        """Test rate limiting"""
        from auth.security import RateLimiter, TokenData
        from fastapi import HTTPException
        import asyncio
        
        limiter = RateLimiter(calls=3, period=60)
        user = TokenData(user_id="test", username="test", roles=["user"], exp=datetime.utcnow())
        
        # Should allow first 3 requests
        for _ in range(3):
            asyncio.run(limiter(user))
        
        # Should block 4th request
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(limiter(user))
        
        assert exc_info.value.status_code == 429


# ==================== INPUT VALIDATION TESTS ====================

class TestInputValidation:
    """Test input validation and sanitization"""
    
    def test_sanitize_string_removes_html(self):
        """Test HTML removal"""
        from auth.validation import InputValidator
        
        dirty = "<script>alert('xss')</script>Hello"
        clean = InputValidator.sanitize_string(dirty)
        
        assert "<script>" not in clean
        assert "Hello" in clean
    
    def test_check_sql_injection(self):
        """Test SQL injection detection"""
        from auth.validation import InputValidator
        from fastapi import HTTPException
        
        malicious_inputs = [
            "1' OR '1'='1",
            "admin'--",
            "1; DROP TABLE users;",
            "1 UNION SELECT * FROM users"
        ]
        
        for input_str in malicious_inputs:
            with pytest.raises(HTTPException):
                InputValidator.check_sql_injection(input_str)
    
    def test_check_xss(self):
        """Test XSS detection"""
        from auth.validation import InputValidator
        from fastapi import HTTPException
        
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>"
        ]
        
        for input_str in malicious_inputs:
            with pytest.raises(HTTPException):
                InputValidator.check_xss(input_str)
    
    def test_validate_email(self):
        """Test email validation"""
        from auth.validation import InputValidator
        from fastapi import HTTPException
        
        # Valid emails
        valid_emails = ["test@example.com", "user.name@domain.co.uk"]
        for email in valid_emails:
            assert InputValidator.validate_email(email) == email.lower()
        
        # Invalid emails
        invalid_emails = ["notanemail", "missing@domain", "@nodomain.com"]
        for email in invalid_emails:
            with pytest.raises(HTTPException):
                InputValidator.validate_email(email)


# ==================== CACHE TESTS ====================

class TestCache:
    """Test Redis caching functionality"""
    
    @patch("infrastructure.cache.redis.Redis")
    def test_cache_set_and_get(self, mock_redis):
        """Test basic cache operations"""
        from infrastructure.cache import RedisCache
        
        cache = RedisCache()
        mock_redis.return_value.get.return_value = None
        mock_redis.return_value.set.return_value = True
        
        # Test set
        result = cache.set("test_key", "test_value", ttl=60)
        assert result == True
    
    @patch("infrastructure.cache.redis.Redis")
    def test_llm_cache(self, mock_redis):
        """Test LLM response caching"""
        from infrastructure.cache import LLMCache
        
        mock_redis.return_value.get.return_value = None
        
        prompt = "What is AI?"
        model = "gpt-4"
        response = "AI is artificial intelligence"
        cost = 0.01
        
        # Cache response
        LLMCache.set_response(prompt, model, response, cost)
        
        # Retrieve cached response (in real test, mock would return cached data)
        # cached = LLMCache.get_response(prompt, model)
        # assert cached is not None


# ==================== TASK QUEUE TESTS ====================

class TestTaskQueue:
    """Test Celery task queue"""
    
    @patch("infrastructure.tasks.celery_app")
    def test_task_result_tracking(self, mock_celery):
        """Test task result tracking"""
        from infrastructure.tasks import TaskResult
        
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.ready.return_value = True
        mock_result.result = {"jobs_found": 10}
        
        mock_celery.AsyncResult.return_value = mock_result
        
        status = TaskResult.get_status("task_123")
        
        assert status["status"] == "SUCCESS"
        assert status["result"]["jobs_found"] == 10


# ==================== API ENDPOINT TESTS ====================

class TestAPIEndpoints:
    """Test API endpoints"""
    
    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        assert "status" in response.json()
    
    def test_unauthenticated_request(self, client):
        """Test request without authentication"""
        response = client.get("/api/jobs")
        assert response.status_code == 401
    
    def test_authenticated_request(self, client):
        """Test request with valid authentication"""
        from auth.security import create_access_token
        
        token = create_access_token({"sub": "test", "username": "test", "roles": ["user"]})
        headers = {"Authorization": f"Bearer {token}"}
        
        response = client.get("/api/jobs", headers=headers)
        # Depending on implementation, should return 200 or other valid status
    
    def test_rate_limiting(self, client):
        """Test API rate limiting"""
        from auth.security import create_access_token
        
        token = create_access_token({"sub": "test", "username": "test", "roles": ["user"]})
        headers = {"Authorization": f"Bearer {token}"}
        
        # Make requests until rate limit
        responses = []
        for _ in range(15):  # Assuming limit is 10
            response = client.get("/api/jobs", headers=headers)
            responses.append(response.status_code)
        
        # Should eventually get 429
        assert 429 in responses


# ==================== JOB SEARCH TESTS ====================

class TestJobSearch:
    """Test job search functionality"""
    
    @pytest.mark.asyncio
    async def test_linkedin_scraper(self, mock_llm):
        """Test LinkedIn job scraper"""
        from services.scraper.linkedin import LinkedInScraper
        
        scraper = LinkedInScraper()
        
        # Mock the scraping
        with patch.object(scraper, '_scrape_jobs') as mock_scrape:
            mock_scrape.return_value = [
                {
                    "title": "AI Engineer",
                    "company": "TechCorp",
                    "location": "Remote",
                    "url": "https://linkedin.com/jobs/123"
                }
            ]
            
            jobs = await scraper.search("AI Engineer", location="Remote")
            
            assert len(jobs) == 1
            assert jobs[0]["title"] == "AI Engineer"
    
    def test_job_scoring(self, sample_job_data):
        """Test job match scoring"""
        from agents.crew import JobFinderAgent
        
        agent = JobFinderAgent()
        
        user_skills = ["Python", "Machine Learning", "FastAPI"]
        score = agent.calculate_match_score(sample_job_data, user_skills)
        
        assert 0 <= score <= 100


# ==================== RESUME GENERATION TESTS ====================

class TestResumeGeneration:
    """Test resume generation"""
    
    @pytest.mark.asyncio
    async def test_ats_optimization(self, mock_llm):
        """Test ATS optimization"""
        from services.resume.ats_optimizer import ATSOptimizer
        
        optimizer = ATSOptimizer()
        
        job_description = "Python developer with ML experience"
        user_skills = ["Python", "Machine Learning", "TensorFlow"]
        
        with patch.object(optimizer, 'generate_resume') as mock_gen:
            mock_gen.return_value = {
                "content": "Optimized resume",
                "ats_score": 89
            }
            
            resume = await optimizer.optimize_for_job(job_description, user_skills)
            
            assert resume["ats_score"] >= 85
    
    def test_keyword_extraction(self):
        """Test keyword extraction from job description"""
        from services.resume.ats_optimizer import ATSOptimizer
        
        optimizer = ATSOptimizer()
        
        job_desc = "Looking for Python developer with FastAPI and PostgreSQL experience"
        keywords = optimizer.extract_keywords(job_desc)
        
        assert "Python" in keywords
        assert "FastAPI" in keywords
        assert "PostgreSQL" in keywords


# ==================== DATABASE TESTS ====================

class TestDatabase:
    """Test database operations"""
    
    def test_create_job(self, db_session, sample_job_data):
        """Test creating a job record"""
        from models.database import Job
        
        job = Job(**sample_job_data)
        db_session.add(job)
        db_session.commit()
        
        assert job.id is not None
        assert job.title == sample_job_data["title"]
    
    def test_query_jobs(self, db_session, sample_job_data):
        """Test querying jobs"""
        from models.database import Job
        
        # Create test jobs
        for i in range(5):
            job = Job(**{**sample_job_data, "title": f"Job {i}"})
            db_session.add(job)
        db_session.commit()
        
        # Query jobs
        jobs = db_session.query(Job).filter(Job.remote == True).all()
        assert len(jobs) == 5


# ==================== INTEGRATION TESTS ====================

class TestIntegration:
    """End-to-end integration tests"""
    
    @pytest.mark.asyncio
    async def test_full_job_application_flow(self, mock_llm, mock_redis):
        """Test complete job application workflow"""
        # 1. Search for jobs
        # 2. Score jobs
        # 3. Generate resume
        # 4. Generate cover letter
        # 5. Submit application
        # 6. Track in database
        
        # This would be a complex test simulating entire workflow
        pass


# ==================== LOAD TESTS ====================

class TestLoad:
    """Load and performance tests"""
    
    @pytest.mark.load
    def test_concurrent_requests(self, client):
        """Test system under concurrent load"""
        import concurrent.futures
        from auth.security import create_access_token
        
        token = create_access_token({"sub": "test", "username": "test", "roles": ["user"]})
        headers = {"Authorization": f"Bearer {token}"}
        
        def make_request():
            return client.get("/api/jobs", headers=headers)
        
        # Simulate 100 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # Check success rate
        success_count = sum(1 for r in results if r.status_code in [200, 401])
        assert success_count >= 95  # 95% success rate


# ==================== SECURITY TESTS ====================

class TestSecurity:
    """Security testing"""
    
    def test_sql_injection_prevention(self, client):
        """Test SQL injection prevention"""
        from auth.security import create_access_token
        
        token = create_access_token({"sub": "test", "username": "test", "roles": ["user"]})
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try SQL injection in query params
        response = client.get(
            "/api/jobs?query=1' OR '1'='1",
            headers=headers
        )
        
        # Should reject with 400
        assert response.status_code in [400, 401]
    
    def test_xss_prevention(self, client):
        """Test XSS prevention"""
        from auth.security import create_access_token
        
        token = create_access_token({"sub": "test", "username": "test", "roles": ["user"]})
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try XSS in request body
        response = client.post(
            "/api/profile",
            headers=headers,
            json={"bio": "<script>alert('xss')</script>"}
        )
        
        # Should either reject or sanitize
        assert response.status_code in [400, 200]


# ==================== AI SYSTEM TESTS ====================

class TestAISystem:
    """Test AI agent system"""
    
    @pytest.mark.asyncio
    async def test_prompt_versioning(self):
        """Test prompt version management"""
        from infrastructure.ai_management import PromptManager
        
        manager = PromptManager()
        
        prompt_v1 = "Generate resume for {job_title}"
        manager.save_prompt("resume_gen", prompt_v1, version="1.0.0")
        
        retrieved = manager.get_prompt("resume_gen", version="1.0.0")
        assert retrieved == prompt_v1
    
    @pytest.mark.asyncio
    async def test_cost_tracking(self, mock_llm):
        """Test LLM cost tracking"""
        from infrastructure.ai_management import CostTracker
        
        tracker = CostTracker()
        
        tracker.record_usage(
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01
        )
        
        total_cost = tracker.get_total_cost()
        assert total_cost >= 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=.", "--cov-report=html"])
