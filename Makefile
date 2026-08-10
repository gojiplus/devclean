.PHONY: help install install-dev test lint format type-check security clean build docs pre-commit ci-docker

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package
	uv sync

install-dev:  ## Install development dependencies
	uv sync --all-extras
	uv run pre-commit install

test:  ## Run tests
	uv run pytest -v --cov=devclean --cov-report=html --cov-report=term-missing

test-quick:  ## Run tests without coverage
	uv run pytest -v

lint:  ## Run linting checks
	uv run ruff check .
	uv run ruff format --check .

format:  ## Format code
	uv run ruff format .
	uv run ruff check --fix .

type-check:  ## Run type checking
	uv run mypy devclean/

security:  ## Run security checks
	uvx bandit -c pyproject.toml -r devclean/

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
	uv build

docs:  ## Generate documentation
	@echo "Documentation would be generated here"

pre-commit:  ## Run pre-commit hooks on all files
	uv run pre-commit run --all-files

ci-docker:  ## Run CI in Docker (local testing)
	docker run --rm -v $(PWD):/workspace -w /workspace ghcr.io/astral-sh/uv:python3.11-bookworm bash -c "\
		uv sync --all-extras && \
		uv run ruff check . && \
		uv run mypy devclean/ && \
		uv run pytest -v"

check-all: lint type-check security test  ## Run all checks

release-check:  ## Check if ready for release
	@echo "Checking if ready for release..."
	make clean
	make check-all
	make build
	uvx twine check dist/*
	@echo "✅ Ready for release!"

# Development helpers
dev-setup:  ## Complete development setup
	make install-dev
	uv run pre-commit install
	@echo "✅ Development environment ready!"

dev-check:  ## Quick development checks
	make format
	make lint
	make test-quick
