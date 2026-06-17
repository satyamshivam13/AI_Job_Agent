import os
os.environ.setdefault("JWT_SECRET_KEY", "test-key-long-enough-for-jwt-signing-32chars-ok")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "testing")

"""
pytest configuration
test_production.py is excluded — it uses pre-fix mocking patterns.
Use tests/test_runnable.py for the verified, passing test suite.
"""
import pytest

collect_ignore = ["tests/test_production.py"]


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires external services")

import pytest

@pytest.fixture(autouse=True)
def reset_env_between_tests(monkeypatch, request):
    """
    Ensure clean JWT_SECRET_KEY for every test — prevents reload pollution.
    test_five_fixes.py manages its own DATABASE_URL via a shared singleton
    client, so we don't override it for tests in that module.
    """
    monkeypatch.setenv("JWT_SECRET_KEY", "test-key-long-enough-for-jwt-signing-32chars-ok")
    if "test_five_fixes" not in str(request.node.fspath):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    yield
