# Detect if venv exists and use it, otherwise use system Python
PYTHON := $(shell if [ -d venv ]; then echo venv/bin/python; else echo python3; fi)

setup:
	virtualenv -p python3 venv
	venv/bin/pip install -r requirements.txt

run:
	$(PYTHON) -m uvicorn app.main:app --reload --port 3000

# Development mode (with hot reload)
up:
	docker compose up -d

# Production mode (multi-worker, no reload)
up-prod:
	docker compose --profile prod up -d epguides-api-prod redis

down:
	docker compose down --remove-orphans

logs:
	docker compose logs -f epguides-api 2>/dev/null || docker compose logs -f epguides-api-prod

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
