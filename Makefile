# Detect if venv exists and use it, otherwise use system Python
PYTHON := $(shell if [ -d venv ]; then echo venv/bin/python; else echo python3; fi)

setup:
	virtualenv -p python3 venv
	venv/bin/pip install -r requirements.txt

run:
	$(PYTHON) -m uvicorn app.main:app --reload

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
