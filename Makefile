.PHONY: help install install-dev test lint format type-check security clean build docs pre-commit ci-docker

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package
	pip install -e .

install-dev:  ## Install development dependencies
	pip install -e ".[dev]"
	pre-commit install

test:  ## Run tests
	pytest -v --cov=devclean --cov-report=html --cov-report=term-missing

test-quick:  ## Run tests without coverage
	pytest -v

lint:  ## Run linting checks
	ruff check .
	ruff format --check .

format:  ## Format code
	ruff format .
	ruff check --fix .

type-check:  ## Run type checking
	mypy devclean/

security:  ## Run security checks
	bandit -r devclean/ --skip B404,B603,B607,B110,B112

clean:  ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build:  ## Build package
	python -m build

docs:  ## Generate documentation
	@echo "Documentation would be generated here"

pre-commit:  ## Run pre-commit hooks on all files
	pre-commit run --all-files

ci-docker:  ## Run CI in Docker (local testing)
	docker run --rm -v $(PWD):/workspace -w /workspace python:3.10-slim bash -c "\
		apt-get update && apt-get install -y make git && \
		pip install -e .[dev] && \
		make lint && \
		make type-check && \
		make test"

check-all: lint type-check security test  ## Run all checks

release-check:  ## Check if ready for release
	@echo "Checking if ready for release..."
	make clean
	make check-all
	make build
	twine check dist/*
	@echo "✅ Ready for release!"

# Development helpers
dev-setup:  ## Complete development setup
	make install-dev
	pre-commit install
	@echo "✅ Development environment ready!"

dev-check:  ## Quick development checks
	make format
	make lint
	make test-quick
