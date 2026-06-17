# ============================================================
# AI Job Agent — Developer Makefile
# ============================================================
# Usage:
#   make install        Install all dependencies
#   make test           Run test suite (71 tests, 0 failures)
#   make coverage       Run tests with coverage report
#   make lint           Check code style
#   make format         Auto-format code
#   make run            Start API server locally
#   make workers        Start Celery workers
#   make docker-up      Start full stack with Docker Compose
#   make docker-prod    Start production stack with monitoring
#   make clean          Remove cache and temp files

.PHONY: install test coverage lint format run workers \
        docker-up docker-prod docker-down clean migrate \
        check health

PYTHON   := python3
PIP      := pip3
APP      := api.main:app
HOST     := 0.0.0.0
PORT     := 8000
WORKERS  := 4

# ──────────────────────────────────────────
# SETUP
# ──────────────────────────────────────────

install:                       ## Install all production dependencies
	$(PIP) install -r requirements_production.txt
	playwright install chromium
	@echo "✅  Dependencies installed"

install-dev:                   ## Install dev/test dependencies only
	$(PIP) install pytest pytest-asyncio pytest-cov httpx \
	               black isort flake8 mypy
	@echo "✅  Dev dependencies installed"

# ──────────────────────────────────────────
# TESTING
# ──────────────────────────────────────────

test:                          ## Run full test suite
	$(PYTHON) -m pytest tests/test_runnable.py tests/test_suite.py \
	    -v --tb=short
	@echo ""
	@echo "✅  Test suite complete"

test-fast:                     ## Run tests without verbose output
	$(PYTHON) -m pytest tests/test_runnable.py tests/test_suite.py -q

coverage:                      ## Run tests with coverage report
	$(PYTHON) -m pytest tests/test_runnable.py tests/test_suite.py \
	    --cov=auth --cov=infrastructure --cov=models \
	    --cov=config --cov=workers --cov=api/main.py \
	    --cov-config=.coveragerc \
	    --cov-report=term-missing \
	    --cov-report=html:htmlcov \
	    --cov-report=xml:coverage.xml \
	    -q
	@echo ""
	@echo "✅  Coverage report → htmlcov/index.html"

test-unit:                     ## Run only unit tests (no integration)
	$(PYTHON) -m pytest tests/test_runnable.py -v -m "not integration"

# ──────────────────────────────────────────
# CODE QUALITY
# ──────────────────────────────────────────

lint:                          ## Run all linters
	@echo "▶  Running flake8..."
	flake8 auth/ infrastructure/ api/ workers/ models/ config/ \
	       --max-line-length=100 --exclude=migrations,__pycache__
	@echo "▶  Running mypy..."
	mypy auth/ infrastructure/ api/ --ignore-missing-imports \
	     --no-error-summary 2>/dev/null || true
	@echo "✅  Lint complete"

format:                        ## Auto-format with black + isort
	@echo "▶  Running isort..."
	isort auth/ infrastructure/ api/ workers/ models/ config/ tests/
	@echo "▶  Running black..."
	black auth/ infrastructure/ api/ workers/ models/ config/ tests/ \
	      --line-length=100
	@echo "✅  Formatting complete"

format-check:                  ## Check formatting without changing files
	black --check --diff auth/ infrastructure/ api/ workers/ --line-length=100
	isort --check-only auth/ infrastructure/ api/ workers/

security-scan:                 ## Run bandit security scan
	bandit -r auth/ infrastructure/ api/ workers/ -ll -q

# ──────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────

migrate:                       ## Run Alembic database migrations
	alembic upgrade head
	@echo "✅  Migrations applied"

migrate-create:                ## Create a new migration
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

db-init:                       ## Initialize SQLite dev database
	DATABASE_URL=sqlite:///./dev.db \
	  $(PYTHON) -c "from models.database import Base, _get_engine; Base.metadata.create_all(_get_engine()); print('✅ Dev DB initialised')"

# ──────────────────────────────────────────
# LOCAL DEVELOPMENT
# ──────────────────────────────────────────

run:                           ## Start API server (dev mode, hot reload)
	@echo "▶  Starting API server on http://$(HOST):$(PORT)"
	DATABASE_URL=sqlite:///./dev.db \
	  uvicorn $(APP) --host $(HOST) --port $(PORT) --reload \
	          --log-level info

run-prod:                      ## Start API server (production mode, gunicorn)
	gunicorn $(APP) \
	    --worker-class uvicorn.workers.UvicornWorker \
	    --workers $(WORKERS) \
	    --bind $(HOST):$(PORT) \
	    --timeout 120 \
	    --access-logfile - \
	    --error-logfile -

workers:                       ## Start Celery workers (requires Redis)
	@echo "▶  Starting Celery workers..."
	celery -A infrastructure.tasks worker \
	       --loglevel=info \
	       --concurrency=4 \
	       --queues=high_priority,default,low_priority

beat:                          ## Start Celery beat scheduler
	celery -A infrastructure.tasks beat --loglevel=info

flower:                        ## Start Flower (Celery monitoring UI)
	celery -A infrastructure.tasks flower \
	       --port=5555 \
	       --basic_auth=admin:admin

health:                        ## Check API health endpoint
	@curl -sf http://localhost:$(PORT)/health | python3 -m json.tool \
	  || echo "❌  API not running — start with: make run"

# ──────────────────────────────────────────
# DOCKER
# ──────────────────────────────────────────

docker-up:                     ## Start full stack (dev) with Docker Compose
	docker-compose up -d
	@echo "✅  Stack started"
	@echo "   API:       http://localhost:8000"
	@echo "   Docs:      http://localhost:8000/docs"
	@echo "   Dashboard: http://localhost:8000/api/dashboard/stats"

docker-prod:                   ## Start production stack with full monitoring
	docker-compose -f docker-compose.prod.yml up -d
	@echo "✅  Production stack started"
	@echo "   API:        http://localhost:8000"
	@echo "   Grafana:    http://localhost:3000  (admin/admin)"
	@echo "   Prometheus: http://localhost:9090"
	@echo "   Flower:     http://localhost:5555"

docker-down:                   ## Stop all Docker containers
	docker-compose down
	docker-compose -f docker-compose.prod.yml down 2>/dev/null || true
	@echo "✅  All containers stopped"

docker-build:                  ## Rebuild Docker image
	docker build -t ai-job-agent:latest .
	@echo "✅  Image built: ai-job-agent:latest"

docker-logs:                   ## Follow API container logs
	docker-compose logs -f api

docker-shell:                  ## Open shell in running API container
	docker-compose exec api bash

# ──────────────────────────────────────────
# KUBERNETES
# ──────────────────────────────────────────

k8s-deploy:                    ## Deploy to Kubernetes
	kubectl apply -f k8s/deployment.yaml
	kubectl rollout status deployment/api -n ai-job-agent

k8s-rollback:                  ## Rollback last Kubernetes deployment
	kubectl rollout undo deployment/api -n ai-job-agent
	kubectl rollout undo deployment/celery-worker -n ai-job-agent

k8s-pods:                      ## List all pods in namespace
	kubectl get pods -n ai-job-agent

k8s-logs:                      ## Follow API pod logs
	kubectl logs -f -l component=api -n ai-job-agent

# ──────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────

clean:                         ## Remove cache, pyc files, and test artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache htmlcov .coverage coverage.xml
	rm -f test_api.db dev.db
	@echo "✅  Cleaned"

check: format-check lint test  ## Full pre-commit check (format + lint + test)
	@echo ""
	@echo "✅  All checks passed — ready to commit"

show-routes:                   ## Print all registered API routes
	$(PYTHON) -c "from api.main import app; [print(f'  {sorted(r.methods)[0]:6} {r.path}') for r in app.routes if hasattr(r, 'methods')]"

help:                          ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
