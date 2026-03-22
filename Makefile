.PHONY: help install dev-install up down status serve query manifest lint format test coverage seed

PYTHON := python
PIP    := pip
PYTEST := pytest

help:
	@echo "OpenCrab - MetaOntology MCP Server"
	@echo ""
	@echo "Usage:"
	@echo "  make install       Install package"
	@echo "  make dev-install   Install with dev extras"
	@echo "  make up            Start all Docker services"
	@echo "  make down          Stop all Docker services"
	@echo "  make status        Check store connections"
	@echo "  make serve         Start MCP server on stdio"
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

up:
	docker-compose up -d
	@echo "Services starting... run 'make status' to check readiness."

down:
	docker-compose down

status:
	$(PYTHON) -m opencrab.cli status

serve:
	$(PYTHON) -m opencrab.cli serve

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
