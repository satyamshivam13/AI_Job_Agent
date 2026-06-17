"""
Locust Load Testing Configuration
Run: locust -f tests/locustfile.py --host http://localhost:8000
"""

from locust import HttpUser, task, between, events
from locust.runners import MasterRunner
import json
import random
import time


# ==================== SHARED DATA ====================

JOB_QUERIES = [
    "Software Engineer",
    "Data Scientist",
    "Product Manager",
    "AI Engineer",
    "Backend Developer",
    "DevOps Engineer",
    "Machine Learning Engineer",
    "Full Stack Developer",
]

LOCATIONS = [
    "San Francisco, CA",
    "New York, NY",
    "Seattle, WA",
    "Austin, TX",
    "Remote",
    "",
]


# ==================== USER BEHAVIORS ====================

class RegularUser(HttpUser):
    """
    Simulates regular API user behavior
    30% of load
    """
    weight = 3
    wait_time = between(1, 3)  # 1-3 seconds between requests

    def on_start(self):
        """Login and get JWT token"""
        response = self.client.post("/auth/token", data={
            "username": "testuser",
            "password": "testpassword"
        })
        if response.status_code == 200:
            self.token = response.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @task(5)
    def check_health(self):
        """Frequent health checks"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")

    @task(3)
    def list_jobs(self):
        """Browse job listings"""
        with self.client.get(
            "/api/jobs?page=1&page_size=20",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in (200, 401):
                response.success()
            else:
                response.failure(f"List jobs failed: {response.status_code}")

    @task(2)
    def search_jobs(self):
        """Search for jobs"""
        query = random.choice(JOB_QUERIES)
        location = random.choice(LOCATIONS)
        remote = random.choice([True, False])

        with self.client.post(
            "/api/jobs/search",
            headers=self.headers,
            json={
                "query": query,
                "location": location,
                "remote": remote,
                "limit": 20
            },
            catch_response=True
        ) as response:
            if response.status_code in (200, 202, 401, 429):
                response.success()
            else:
                response.failure(f"Search failed: {response.status_code}")

    @task(1)
    def get_dashboard(self):
        """Get analytics dashboard"""
        with self.client.get(
            "/api/analytics/dashboard",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in (200, 401):
                response.success()
            else:
                response.failure(f"Dashboard failed: {response.status_code}")


class PowerUser(HttpUser):
    """
    Simulates power user who generates many resumes
    20% of load
    """
    weight = 2
    wait_time = between(2, 5)

    def on_start(self):
        response = self.client.post("/auth/token", data={
            "username": "poweruser",
            "password": "testpassword"
        })
        if response.status_code == 200:
            self.token = response.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.headers = {}
        self.job_ids = [f"job_{i}" for i in range(1, 20)]

    @task(4)
    def generate_resume(self):
        """Generate ATS-optimized resume"""
        job_id = random.choice(self.job_ids)
        variant = random.choice(["aggressive", "balanced", "conservative"])

        with self.client.post(
            "/api/resumes/generate",
            headers=self.headers,
            json={
                "job_id": job_id,
                "variant": variant
            },
            catch_response=True,
            name="/api/resumes/generate"
        ) as response:
            if response.status_code in (200, 202, 401, 429):
                response.success()
            else:
                response.failure(f"Resume gen failed: {response.status_code}")

    @task(2)
    def list_resumes(self):
        """List generated resumes"""
        with self.client.get(
            "/api/resumes",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in (200, 401):
                response.success()
            else:
                response.failure(f"List resumes failed: {response.status_code}")

    @task(1)
    def submit_application(self):
        """Submit job application"""
        with self.client.post(
            "/api/applications/submit",
            headers=self.headers,
            json={
                "job_id": random.choice(self.job_ids),
                "resume_id": f"resume_{random.randint(1, 10)}"
            },
            catch_response=True
        ) as response:
            if response.status_code in (200, 202, 401, 429):
                response.success()
            else:
                response.failure(f"Application failed: {response.status_code}")


class UnauthenticatedUser(HttpUser):
    """
    Simulates unauthenticated traffic / bots
    50% of load — tests rate limiting and auth enforcement
    """
    weight = 5
    wait_time = between(0.5, 2)

    @task(5)
    def health_check(self):
        """Public health endpoint"""
        self.client.get("/health")

    @task(3)
    def try_auth_bypass(self):
        """Attempt to access protected endpoint without auth"""
        with self.client.get(
            "/api/jobs",
            catch_response=True
        ) as response:
            # 401 is EXPECTED — auth is working
            if response.status_code == 401:
                response.success()
            elif response.status_code == 200:
                response.failure("Auth bypass — should have returned 401!")
            else:
                response.success()

    @task(1)
    def try_invalid_token(self):
        """Test invalid JWT rejection"""
        with self.client.get(
            "/api/jobs",
            headers={"Authorization": "Bearer invalid.jwt.token"},
            catch_response=True
        ) as response:
            if response.status_code in (401, 403):
                response.success()
            else:
                response.failure(f"Invalid token not rejected: {response.status_code}")

    @task(1)
    def hammer_rate_limits(self):
        """Rapid-fire requests to test rate limiting"""
        for _ in range(5):
            with self.client.post(
                "/auth/token",
                data={"username": "hacker", "password": "wrong"},
                catch_response=True,
                name="/auth/token [rate limit test]"
            ) as response:
                if response.status_code in (200, 401, 429):
                    response.success()
                else:
                    response.failure(f"Unexpected: {response.status_code}")


# ==================== LOAD TEST SCENARIOS ====================

class StressTest(HttpUser):
    """
    Stress test — gradually ramps up to find breaking point
    Run with: locust -f tests/locustfile.py --users 200 --spawn-rate 10
    """
    weight = 1
    wait_time = between(0.1, 0.5)  # Very aggressive

    def on_start(self):
        response = self.client.post("/auth/token", data={
            "username": "stresstest",
            "password": "testpassword"
        })
        self.headers = {}
        if response.status_code == 200:
            token = response.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {token}"}

    @task
    def mixed_load(self):
        """Mixed workload for stress testing"""
        choice = random.randint(1, 10)
        if choice <= 5:
            self.client.get("/health")
        elif choice <= 7:
            self.client.get("/api/jobs", headers=self.headers)
        elif choice <= 9:
            self.client.post(
                "/api/jobs/search",
                headers=self.headers,
                json={"query": random.choice(JOB_QUERIES), "limit": 10}
            )
        else:
            self.client.get("/api/analytics/dashboard", headers=self.headers)


# ==================== CUSTOM METRICS ====================

@events.request.add_listener
def on_request(request_type, name, response_time, response_length, **kwargs):
    """Log slow requests for analysis"""
    if response_time > 1000:  # >1 second
        print(f"⚠️  SLOW: {request_type} {name} took {response_time:.0f}ms")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Print test configuration at start"""
    print("\n" + "="*60)
    print("🚀 LOAD TEST STARTING")
    print("="*60)
    print(f"Host: {environment.host}")
    print(f"Users: {environment.runner.target_user_count if hasattr(environment, 'runner') else 'unknown'}")
    print("="*60 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary at end"""
    stats = environment.runner.stats
    print("\n" + "="*60)
    print("📊 LOAD TEST COMPLETE")
    print("="*60)
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Failures: {stats.total.num_failures}")
    print(f"Failure rate: {stats.total.fail_ratio:.1%}")
    print(f"Avg response: {stats.total.avg_response_time:.0f}ms")
    print(f"p95 response: {stats.total.get_response_time_percentile(0.95):.0f}ms")
    print(f"p99 response: {stats.total.get_response_time_percentile(0.99):.0f}ms")
    print("="*60 + "\n")

    # Fail if error rate too high
    if stats.total.fail_ratio > 0.05:
        print(f"❌ FAIL: Error rate {stats.total.fail_ratio:.1%} > 5% threshold")
    else:
        print(f"✅ PASS: Error rate {stats.total.fail_ratio:.1%} within threshold")
