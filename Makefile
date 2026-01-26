.PHONY: help setup up down up-prod logs test lint format fix docs docs-build
.PHONY: cache-clear deploy-prod doctor urls open clean

.DEFAULT_GOAL := help

PYTHON := $(shell if [ -d venv ]; then echo venv/bin/python; else echo python3; fi)

# =============================================================================
# HELP
# =============================================================================

help:
	@echo "Epguides API"
	@echo ""
	@echo "Quick Start:"
	@echo "  make setup          Install venv + pre-commit hooks"
	@echo "  make up             Start dev environment"
	@echo "  make test           Run tests (100% coverage)"
	@echo "  make doctor         Check environment health"
	@echo ""
	@echo "Development:"
	@echo "  make up             Start dev (Docker + hot reload)"
	@echo "  make down           Stop all services"
	@echo "  make logs           View logs"
	@echo "  make run            Run locally without Docker"
	@echo ""
	@echo "Quality:"
	@echo "  make fix            Format + lint (ruff)"
	@echo "  make lint           Lint only"
	@echo "  make format         Format only"
	@echo "  make test           Run tests with coverage"
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

# =============================================================================
# DOCTOR
# =============================================================================

doctor:
	@echo "Environment Health Check"
	@echo ""
	@printf "Docker:       " && (docker --version >/dev/null 2>&1 && echo "OK" || echo "MISSING")
	@printf "Compose:      " && (docker compose version >/dev/null 2>&1 && echo "OK" || echo "MISSING")
	@printf "Python:       " && ($(PYTHON) --version 2>&1 | head -1 || echo "MISSING")
	@printf "Venv:         " && ([ -d venv ] && echo "OK" || echo "MISSING - run: make setup")
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

# =============================================================================
# SETUP
# =============================================================================

setup:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt
	venv/bin/pre-commit install
	venv/bin/pre-commit install --hook-type commit-msg
	@echo ""
	@echo "Setup complete. Run: make up"

# =============================================================================
# DEVELOPMENT
# =============================================================================

run:
	$(PYTHON) -m uvicorn app.main:app --reload --port 3000

up:
	docker compose up -d
	@echo ""
	@make urls

down:
	docker compose down 2>/dev/null; docker compose -f docker-compose.prod.yml down 2>/dev/null

logs:
	docker compose logs -f

# =============================================================================
# PRODUCTION
# =============================================================================

up-prod:
	docker compose -f docker-compose.prod.yml up -d
	@make urls

deploy-prod:
	docker compose -f docker-compose.prod.yml build --no-cache
	docker compose -f docker-compose.prod.yml up -d
	@sleep 3
	@make cache-clear
	@echo "Deployment complete"

cache-clear:
	docker exec $$(docker ps -qf "name=redis") redis-cli FLUSHALL 2>/dev/null || echo "Redis not running"

# =============================================================================
# CODE QUALITY
# =============================================================================

test:
	PYTHONPATH=. $(PYTHON) -m pytest --cov=app --cov-report=term-missing

format:
	$(PYTHON) -m ruff format app/

lint:
	$(PYTHON) -m ruff check app/

fix:
	$(PYTHON) -m ruff check --fix app/
	$(PYTHON) -m ruff format app/

# =============================================================================
# DOCS
# =============================================================================

docs:
	$(PYTHON) -m mkdocs serve

docs-build:
	$(PYTHON) -m mkdocs build

# =============================================================================
# CLEANUP
# =============================================================================

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .coverage
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -delete
