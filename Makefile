.PHONY: help setup up dev down stop build up-prod logs run test lint format format-check fix check coverage ci
.PHONY: docs docs-build cache-clear deploy-prod doctor urls open clean audit-osv

.DEFAULT_GOAL := help

UV := uv
RUN := $(UV) run
DOCS_RUN := $(UV) run --no-project --isolated --with-requirements docs/requirements.txt

help:
	@echo "Epguides API"
	@echo ""
	@echo "Quick Start:"
	@echo "  make setup          Install venv + pre-commit hooks"
	@echo "  make up             Start dev environment"
	@echo "  make test           Run tests (95% coverage floor via pre-commit/CI)"
	@echo "  make doctor         Check environment health"
	@echo ""
	@echo "Development:"
	@echo "  make up             Start dev (Docker + hot reload)"
	@echo "  make dev            Alias for 'up'"
	@echo "  make down           Stop all services"
	@echo "  make stop           Alias for 'down'"
	@echo "  make build          Build production image without starting"
	@echo "  make logs           View logs"
	@echo "  make run            Run locally without Docker"
	@echo ""
	@echo "Quality:"
	@echo "  make ci             Run all checks (format + lint + test)"
	@echo "  make check          Run format + lint checks (no tests)"
	@echo "  make fix            Auto-fix format + lint (ruff)"
	@echo "  make lint           Lint only (ruff check)"
	@echo "  make format         Format only (ruff format)"
	@echo "  make format-check   Check formatting without changes"
	@echo "  make test           Run tests with coverage"
	@echo "  make coverage       Run tests with HTML coverage report"
	@echo "  make audit-osv      Local dependency-CVE check (OSV-Scanner vs uv.lock)"
	@echo ""
	@echo "Production:"
	@echo "  make up-prod        Start production"
	@echo "  make deploy-prod    Build, restart, clear cache"
	@echo "  make cache-clear    Flush Redis"
	@echo ""
	@echo "Docs:"
	@echo "  make docs           Serve docs locally"
	@echo "  make docs-build     Build static docs"
	@echo ""
	@echo "Other:"
	@echo "  make urls           Show service URLs"
	@echo "  make open           Open Swagger in browser"
	@echo "  make clean          Remove cache files"

doctor:
	@echo "Environment Health Check"
	@echo ""
	@printf "Docker:       " && (docker --version >/dev/null 2>&1 && echo "OK" || echo "MISSING")
	@printf "Compose:      " && (docker compose version >/dev/null 2>&1 && echo "OK" || echo "MISSING")
	@printf "uv:           " && ($(UV) --version 2>&1 | head -1 || echo "MISSING - install: https://docs.astral.sh/uv/")
	@printf "Python:       " && ($(RUN) python --version 2>&1 | head -1 || echo "MISSING - run: make setup")
	@printf ".venv:        " && ([ -d .venv ] && echo "OK" || echo "MISSING - run: make setup")
	@printf "Pre-commit:   " && ([ -f .git/hooks/pre-commit ] && echo "OK" || echo "MISSING - run: make setup")
	@echo ""
	@echo "Services:"
	@printf "  API:        " && (curl -sf http://localhost:3000/health >/dev/null 2>&1 && echo "RUNNING http://localhost:3000" || echo "STOPPED")
	@printf "  Redis:      " && (docker exec $$(docker ps -qf "name=redis" 2>/dev/null) redis-cli ping >/dev/null 2>&1 && echo "RUNNING" || echo "STOPPED")
	@echo ""

urls:
	@echo "Epguides API URLs"
	@echo ""
	@echo "  API:        http://localhost:3000"
	@echo "  Swagger:    http://localhost:3000/docs"
	@echo "  Health:     http://localhost:3000/health"
	@echo "  Shows:      http://localhost:3000/shows"
	@echo ""

open:
	@(command -v xdg-open >/dev/null 2>&1 && xdg-open http://localhost:3000/docs) || \
	 (command -v open >/dev/null 2>&1 && open http://localhost:3000/docs) || \
	 echo "Open http://localhost:3000/docs in your browser"

setup:
	$(UV) sync
	$(RUN) pre-commit install
	$(RUN) pre-commit install --hook-type commit-msg
	@echo ""
	@echo "Setup complete. Run: make up"

run:
	$(RUN) uvicorn app.main:app --reload --port 3000

up:
	docker compose up -d
	@echo ""
	@make urls

dev: up

down:
	docker compose down 2>/dev/null; docker compose -f docker-compose.prod.yml down 2>/dev/null

stop: down

build:
	docker compose -f docker-compose.prod.yml -f docker-compose.build.yml build

logs:
	docker compose logs -f

up-prod:
	docker compose -f docker-compose.prod.yml -f docker-compose.build.yml build
	docker compose -f docker-compose.prod.yml up -d
	@make urls

deploy-prod:
	docker compose -f docker-compose.prod.yml -f docker-compose.build.yml build --no-cache
	docker compose -f docker-compose.prod.yml up -d
	@sleep 3
	@make cache-clear
	@echo "Deployment complete"

cache-clear:
	docker exec $$(docker ps -qf "name=redis") redis-cli FLUSHALL 2>/dev/null || echo "Redis not running"

test:
	d=$$(mktemp -d); \
	COVERAGE_FILE="$$d/.coverage" $(RUN) pytest --cov=app --cov-report=term-missing; \
	rc=$$?; rm -rf "$$d"; exit $$rc

format:
	$(RUN) ruff format app/

format-check:
	$(RUN) ruff format --check app/

lint:
	$(RUN) ruff check app/

fix:
	$(RUN) ruff check --fix app/
	$(RUN) ruff format app/

check: format-check lint
	@echo "All static checks passed"

typecheck:
	$(RUN) mypy app/ --config-file pyproject.toml --exclude 'app/tests/'

coverage:
	d=$$(mktemp -d); \
	COVERAGE_FILE="$$d/.coverage" $(RUN) pytest --cov=app --cov-report=term-missing --cov-report=html; \
	rc=$$?; rm -rf "$$d"; exit $$rc
	@echo "HTML report: htmlcov/index.html"

ci-parity: format-check lint typecheck
	$(RUN) python scripts/check_no_external_llm.py
	$(RUN) python scripts/check_no_private_git_deps.py
	$(RUN) python scripts/check_no_private_git_deps.py --self-test
	$(RUN) python scripts/check_base_image_digest_pin_drift.py
	$(RUN) python scripts/check_ci_resource_sizing.py
	$(RUN) python scripts/check_ci_resource_sizing.py --self-test
	uv run --python 3.12 --no-project python -m py_compile scripts/*.py

ci: format-check lint test
	@echo "All checks passed"

audit-osv:
	bash scripts/audit_osv.sh

docs:
	$(DOCS_RUN) mkdocs serve

docs-build:
	$(DOCS_RUN) mkdocs build --strict

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .coverage htmlcov/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -delete
