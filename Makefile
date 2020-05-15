setup:
	virtualenv -p /usr/bin/python3 venv
	venv/bin/pip install -r requirements.txt

run:
	PYTHONPATH=$(shell pwd) venv/bin/python api/views.py

test:
	PYTHONPATH=$(shell pwd) venv/bin/python api/tests.py
