.PHONY: help install dev-install status serve serve-http query manifest lint format test coverage seed

PYTHON := python
PIP    := pip
PYTEST := pytest

help:
	@echo "OpenCrab - MetaOntology MCP Server"
	@echo ""
	@echo "Usage:"
	@echo "  make install       Install package"
	@echo "  make dev-install   Install with dev extras"
	@echo "  make status        Check store connections"
	@echo "  make serve         Start MCP server on stdio (default)"
	@echo "  make serve-http    Start MCP server over Streamable HTTP"
	@echo "  make manifest      Print MetaOntology grammar"
	@echo "  make seed          Seed databases with example data"
	@echo "  make lint          Run ruff linter"
	@echo "  make format        Run black + isort"
	@echo "  make test          Run test suite"
	@echo "  make coverage      Run tests with coverage report"

install:
	$(PIP) install -e .

dev-install:
	$(PIP) install -e ".[dev]"

status:
	$(PYTHON) -m opencrab.cli status

serve:
	$(PYTHON) -m opencrab.cli serve

serve-http:
	$(PYTHON) -m opencrab.cli serve --transport http

manifest:
	$(PYTHON) -m opencrab.cli manifest

seed:
	$(PYTHON) scripts/seed_ontology.py

lint:
	ruff check opencrab tests

format:
	black opencrab tests scripts
	isort opencrab tests scripts

test:
	$(PYTEST) tests/ -v

coverage:
	$(PYTEST) tests/ --cov=opencrab --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"
