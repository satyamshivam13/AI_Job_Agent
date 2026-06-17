"""
Tests for the 5 production hardening fixes:
  FIX 1 - /apply dispatches async to Celery (with sync fallback)
  FIX 2 - IP rate limiting on /auth/token and /auth/register
  FIX 3 - /auth/register endpoint
  FIX 4 - Security headers middleware
  FIX 5 - No silent AI failures (explicit error states in agents/crew.py)

Design: ONE shared FastAPI app + SQLite DB for the whole module (singleton,
lazily created on first use). This avoids all engine-disposal/teardown
ordering issues entirely. Test isolation comes from unique usernames,
emails, and job records (via time.time_ns() / uuid4) — never from
recreating the database.
"""

import os
import time
import uuid

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "fix-tests-key-long-enough-for-jwt-32chars")
os.environ.setdefault("ENVIRONMENT", "testing")

_DB_PATH = "./test_five_fixes.db"
_CLIENT = None  # module-level singleton


def _reset_rate_limiter():
    """Clear the global login_rate_limiter state between tests."""
    from auth.security import login_rate_limiter
    login_rate_limiter._store.clear()


def _get_client():
    """Return the shared TestClient, creating it on first use."""
    global _CLIENT
    if _CLIENT is not None:
        _reset_rate_limiter()
        return _CLIENT

    os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
    import models.database as dm
    dm._engine = None
    dm._SessionLocal = None
    from models.database import Base, _get_engine
    Base.metadata.create_all(_get_engine())

    from api.main import app
    from fastapi.testclient import TestClient
    _CLIENT = TestClient(app, raise_server_exceptions=False)
    _reset_rate_limiter()
    return _CLIENT


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db_file():
    yield
    try:
        os.remove(_DB_PATH)
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def _reset_rl_before_each_test():
    _reset_rate_limiter()
    yield


def _register(client, suffix=""):
    """Register a unique user, return (token, username)."""
    uname = f"user{time.time_ns()}{suffix}"
    r = client.post(
        f"/auth/register?username={uname}&password=Password123&email={uname}@t.com"
    )
    assert r.status_code == 201, f"Register failed: {r.status_code} {r.text}"
    return r.json()["access_token"], uname


def _make_job():
    """Insert a Job into the shared DB and return its id string."""
    from models.database import SessionLocal, Job, JobStatus
    db = SessionLocal()
    j = Job(
        id=uuid.uuid4(), platform="linkedin",
        url=f"https://li.com/job/{uuid.uuid4().hex[:8]}",
        title="AI Engineer", company="TechCorp", location="Remote",
        status=JobStatus.NEW,
    )
    db.add(j)
    db.commit()
    jid = str(j.id)
    db.close()
    return jid


# ──────────────────────────────────────────────────────────────────────────────
# FIX 1 — Async /apply endpoint with Celery dispatch + sync fallback
# ──────────────────────────────────────────────────────────────────────────────

class TestAsyncApplyEndpoint:

    def test_apply_returns_202_or_200(self):
        from unittest.mock import patch, MagicMock
        client = _get_client()
        token, _ = _register(client)
        jid = _make_job()
        mock_t = MagicMock(); mock_t.id = "task-001"
        with patch("workers.application_submission.submit_application_task.delay",
                   return_value=mock_t):
            r = client.post(f"/api/jobs/{jid}/apply",
                            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in (200, 202), r.text

    def test_apply_response_has_status_field(self):
        from unittest.mock import patch, MagicMock
        client = _get_client()
        token, _ = _register(client)
        jid = _make_job()
        mock_t = MagicMock(); mock_t.id = "task-002"
        with patch("workers.application_submission.submit_application_task.delay",
                   return_value=mock_t):
            r = client.post(f"/api/jobs/{jid}/apply",
                            headers={"Authorization": f"Bearer {token}"})
        assert "status" in r.json()

    def test_apply_queued_with_task_id_when_celery_available(self):
        from unittest.mock import patch, MagicMock
        client = _get_client()
        token, _ = _register(client)
        jid = _make_job()
        mock_t = MagicMock(); mock_t.id = "task-queued-001"
        # Patch both the task .delay AND the circuit breaker (passthrough)
        def _passthrough(fn): return fn  # circuit breaker no-op for test
        with patch("workers.application_submission.submit_application_task.delay",
                   return_value=mock_t),              patch("api.main.api_circuit_breaker", side_effect=_passthrough):
            r = client.post(f"/api/jobs/{jid}/apply",
                            headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        # Either queued (Celery path) or queued_sync (sync fallback) is acceptable
        assert body.get("status") in ("queued", "queued_sync"), body
        # If queued, task_id must be present
        if body.get("status") == "queued":
            assert body.get("task_id") is not None

    def test_sync_fallback_when_celery_unavailable(self):
        from unittest.mock import patch
        client = _get_client()
        token, _ = _register(client)
        jid = _make_job()
        with patch("workers.application_submission.submit_application_task.delay",
                   side_effect=Exception("Redis connection refused")):
            r = client.post(f"/api/jobs/{jid}/apply",
                            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in (200, 202)
        assert r.json().get("status") == "queued_sync"

    def test_duplicate_apply_returns_already_applied(self):
        from unittest.mock import patch
        client = _get_client()
        token, _ = _register(client)
        jid = _make_job()
        with patch("workers.application_submission.submit_application_task.delay",
                   side_effect=Exception("Redis unavailable")):
            r1 = client.post(f"/api/jobs/{jid}/apply",
                             headers={"Authorization": f"Bearer {token}"})
            r2 = client.post(f"/api/jobs/{jid}/apply",
                             headers={"Authorization": f"Bearer {token}"})
        assert r1.json().get("status") == "queued_sync"
        assert r2.json().get("status") == "already_applied", r2.json()

    def test_apply_requires_auth(self):
        client = _get_client()
        jid = _make_job()
        r = client.post(f"/api/jobs/{jid}/apply")
        assert r.status_code == 401

    def test_invalid_job_id_returns_404_or_422(self):
        client = _get_client()
        token, _ = _register(client)
        r = client.post("/api/jobs/not-a-uuid/apply",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in (404, 422)

    def test_task_status_endpoint_reachable(self):
        client = _get_client()
        token, _ = _register(client)
        r = client.get("/api/tasks/fake-task-id",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in (200, 503)


# ──────────────────────────────────────────────────────────────────────────────
# FIX 2 — IP rate limiter
# ──────────────────────────────────────────────────────────────────────────────

class TestIPRateLimiter:

    def test_rate_limiter_class_exists(self):
        from auth.security import IPRateLimiter
        rl = IPRateLimiter(max_requests=5, window_seconds=60)
        assert rl.max_requests == 5
        assert rl.window_seconds == 60

    def test_allows_requests_under_limit(self):
        from auth.security import IPRateLimiter
        from unittest.mock import MagicMock
        import asyncio
        rl = IPRateLimiter(max_requests=3, window_seconds=60)
        req = MagicMock()
        req.client.host = "1.2.3.4"
        for _ in range(3):
            asyncio.run(rl(req))  # must not raise

    def test_blocks_after_limit_exceeded(self):
        from auth.security import IPRateLimiter
        from fastapi import HTTPException
        from unittest.mock import MagicMock
        import asyncio
        rl = IPRateLimiter(max_requests=2, window_seconds=60)
        req = MagicMock()
        req.client.host = f"9.9.9.{time.time_ns() % 255}"
        asyncio.run(rl(req))
        asyncio.run(rl(req))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(rl(req))
        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers

    def test_different_ips_tracked_separately(self):
        from auth.security import IPRateLimiter
        from unittest.mock import MagicMock
        import asyncio
        rl = IPRateLimiter(max_requests=1, window_seconds=60)
        req_a = MagicMock(); req_a.client.host = "10.0.0.1"
        req_b = MagicMock(); req_b.client.host = "10.0.0.2"
        asyncio.run(rl(req_a))  # consumes IP A's quota
        asyncio.run(rl(req_b))  # IP B unaffected — must not raise

    def test_rate_limiter_wired_to_token_endpoint(self):
        import inspect
        from api.main import login
        sig = inspect.signature(login)
        assert "_rate" in sig.parameters, \
            "/auth/token missing _rate=Depends(login_rate_limiter)"

    def test_login_rate_limiter_instance_exported(self):
        from auth.security import login_rate_limiter, IPRateLimiter
        assert isinstance(login_rate_limiter, IPRateLimiter)
        assert login_rate_limiter.max_requests >= 5


# ──────────────────────────────────────────────────────────────────────────────
# FIX 3 — /auth/register endpoint
# ──────────────────────────────────────────────────────────────────────────────

class TestRegistration:

    def test_register_returns_201_and_token(self):
        client = _get_client()
        uname = f"new{time.time_ns()}"
        r = client.post(
            f"/auth/register?username={uname}&password=Password123&email={uname}@t.com"
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "access_token" in body
        assert body.get("token_type") == "bearer"

    def test_register_returns_user_id_and_username(self):
        client = _get_client()
        uname = f"u{time.time_ns()}"
        r = client.post(
            f"/auth/register?username={uname}&password=Password123&email={uname}@t.com"
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body.get("username") == uname
        assert "user_id" in body

    def test_token_from_register_is_valid(self):
        client = _get_client()
        token, _ = _register(client)
        r = client.get("/api/jobs", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"Token rejected: {r.text}"

    def test_duplicate_username_returns_409(self):
        client = _get_client()
        uname = f"dup{time.time_ns()}"
        client.post(
            f"/auth/register?username={uname}&password=Password123&email={uname}@a.com"
        )
        r2 = client.post(
            f"/auth/register?username={uname}&password=Password456&email={uname}b@b.com"
        )
        assert r2.status_code == 409

    def test_duplicate_email_returns_409(self):
        client = _get_client()
        email = f"same{time.time_ns()}@test.com"
        client.post(
            f"/auth/register?username=ea{time.time_ns()}&password=Password123&email={email}"
        )
        r2 = client.post(
            f"/auth/register?username=eb{time.time_ns()}&password=Password456&email={email}"
        )
        assert r2.status_code == 409

    def test_short_password_returns_422(self):
        client = _get_client()
        r = client.post(
            f"/auth/register?username=s{time.time_ns()}&password=short&email=s@t.com"
        )
        assert r.status_code == 422

    def test_register_then_login_flow(self):
        client = _get_client()
        uname = f"fl{time.time_ns()}"
        client.post(
            f"/auth/register?username={uname}&password=Secure1234&email={uname}@t.com"
        )
        r = client.post("/auth/token", data={"username": uname, "password": "Secure1234"})
        assert r.status_code == 200
        assert "access_token" in r.json()


# ──────────────────────────────────────────────────────────────────────────────
# FIX 4 — Security headers middleware
# ──────────────────────────────────────────────────────────────────────────────

class TestSecurityHeaders:

    def test_x_content_type_options_nosniff(self):
        client = _get_client()
        r = client.get("/health")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_deny(self):
        client = _get_client()
        r = client.get("/health")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_xss_protection_header(self):
        client = _get_client()
        r = client.get("/health")
        assert "x-xss-protection" in r.headers

    def test_referrer_policy_present(self):
        client = _get_client()
        r = client.get("/health")
        assert "referrer-policy" in r.headers

    def test_permissions_policy_present(self):
        client = _get_client()
        r = client.get("/health")
        assert "permissions-policy" in r.headers

    def test_headers_on_protected_endpoints(self):
        client = _get_client()
        r = client.get("/api/jobs")  # 401 but headers must still be present
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"

    def test_headers_on_auth_endpoint(self):
        client = _get_client()
        r = client.post("/auth/token", data={"username": "x", "password": "y"})
        assert r.headers.get("x-content-type-options") == "nosniff"


# ──────────────────────────────────────────────────────────────────────────────
# FIX 5 — No silent AI failures (static source inspection — no LLM calls)
# ──────────────────────────────────────────────────────────────────────────────

class TestNoSilentAIFailures:

    @pytest.fixture(scope="class")
    def crew_src(self):
        path = "agents/crew.py"
        if not os.path.exists(path):
            pytest.skip("agents/crew.py not found")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_no_silent_approval_on_json_error(self, crew_src):
        import re
        blocks = re.findall(
            r"except json\.JSONDecodeError.*?(?=\n    def |\nclass |\Z)",
            crew_src, re.DOTALL,
        )
        for block in blocks:
            assert '"approved"' not in block, (
                f"Silent approval found in error handler:\n{block[:300]}"
            )

    def test_no_fabricated_ats_score_70(self, crew_src):
        import re
        blocks = re.findall(
            r"except json\.JSONDecodeError.*?(?=\n    def |\nclass |\Z)",
            crew_src, re.DOTALL,
        )
        for block in blocks:
            assert '"ats_score_estimate": 70' not in block

    def test_job_scorer_sets_score_error_flag(self, crew_src):
        assert '"score_error": True' in crew_src

    def test_resume_optimizer_returns_none_ats_score(self, crew_src):
        assert '"ats_score_estimate": None' in crew_src

    def test_cover_letter_sets_template_fallback_flag(self, crew_src):
        assert '"is_template_fallback": True' in crew_src

    def test_qa_validator_sets_human_review_required(self, crew_src):
        assert '"human_review_required": True' in crew_src

    def test_all_handlers_have_error_indicator(self, crew_src):
        import re
        blocks = re.findall(
            r"except json\.JSONDecodeError.*?(?=\n    def |\nclass |\Z)",
            crew_src, re.DOTALL,
        )
        assert len(blocks) >= 4, f"Expected >=4 handlers, found {len(blocks)}"
        for i, block in enumerate(blocks):
            has_flag = any(f in block for f in [
                'error": True', "error_reason", "human_review_required",
                "is_template_fallback", "score_error", "generation_error",
                "optimization_error", "qa_parse_failed", "llm_parse_error",
            ])
            assert has_flag, f"Handler {i + 1} missing error flag:\n{block[:250]}"
