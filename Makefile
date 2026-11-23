PY ?= .venv/bin/python
HOST ?= 127.0.0.1
PORT ?= 8800

.PHONY: setup dev test showcase screenshots

setup:
	python3 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

dev:
	$(PY) -m uvicorn app.server:app --host $(HOST) --port $(PORT)

test:
	$(PY) -m pytest

showcase:
	$(PY) scripts/build_showcase.py

screenshots:
	$(PY) scripts/screenshots.py
