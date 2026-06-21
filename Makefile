.PHONY: install install-dev run test lint format type-check clean docker-build docker-run help

PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
BLACK := $(VENV)/bin/black
ISORT := $(VENV)/bin/isort
FLAKE8 := $(VENV)/bin/flake8
MYPY := $(VENV)/bin/mypy
STREAMLIT := $(VENV)/bin/streamlit

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Create venv, install dependencies, download spaCy model
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(VENV)/bin/python -m spacy download en_core_web_sm
	@echo "✅ Installation complete. Run: source $(VENV)/bin/activate"

install-dev:  ## Install with dev tools (black, isort, flake8, mypy, pre-commit)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install black isort flake8 mypy pre-commit pytest-cov
	$(VENV)/bin/python -m spacy download en_core_web_sm
	$(VENV)/bin/pre-commit install
	@echo "✅ Dev installation complete."

run:  ## Launch the Streamlit dashboard
	$(STREAMLIT) run app/streamlit_app.py

test:  ## Run the full test suite with coverage
	$(PYTEST) tests/ -v --cov=src --cov-report=term-missing

test-fast:  ## Run tests without coverage (faster)
	$(PYTEST) tests/ -v

lint:  ## Run flake8 and mypy
	$(FLAKE8) src/ app/ tests/
	$(MYPY) src/ --ignore-missing-imports

format:  ## Auto-format with black and isort
	$(BLACK) src/ app/ tests/
	$(ISORT) src/ app/ tests/

format-check:  ## Check formatting without modifying files
	$(BLACK) --check src/ app/ tests/
	$(ISORT) --check-only src/ app/ tests/

clean:  ## Remove build artifacts, __pycache__, .pyc files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleaned."

clean-data:  ## Clear ChromaDB and SQLite (use before a clean demo run)
	rm -rf data/processed/chroma
	rm -f data/processed/signalnoise.db
	@echo "✅ ChromaDB and SQLite cleared."

docker-build:  ## Build the Docker image
	docker build -t signalnoise-ai .

docker-run:  ## Run the Docker container
	docker run -p 8501:8501 --env-file .env signalnoise-ai

docker-compose-up:  ## Start with docker-compose
	docker-compose up --build

reset:  ## Full reset: clean data + restart
	$(MAKE) clean-data
	@echo "Run: make run"
