# Detect if venv exists and use it, otherwise use system Python
PYTHON := $(shell if [ -d venv ]; then echo venv/bin/python; else echo python3; fi)

setup:
	virtualenv -p python3 venv
	venv/bin/pip install -r requirements.txt

run:
	$(PYTHON) -m uvicorn app.main:app --reload --port 3000

# Development (hot reload, lightweight Redis)
up:
	docker compose up -d

# Production (12 workers, 5GB Redis, optimized for 16 cores)
up-prod:
	docker compose -f docker-compose.prod.yml up -d

down:
	docker compose down 2>/dev/null; docker compose -f docker-compose.prod.yml down 2>/dev/null

logs:
	docker compose logs -f

test:
	$(PYTHON) -m pytest

format:
	$(PYTHON) -m black --line-length 120 app/
	$(PYTHON) -m isort app/

lint:
	$(PYTHON) -m ruff check app/

fix:
	$(PYTHON) -m black --line-length 120 app/
	$(PYTHON) -m isort app/
	$(PYTHON) -m ruff check --fix --unsafe-fixes app/

docs:
	$(PYTHON) -m mkdocs serve

docs-build:
	$(PYTHON) -m mkdocs build
