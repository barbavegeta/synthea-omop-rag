# Thin wrapper around the `rwe` CLI and docker compose. The CLI is the real entrypoint.
PROFILE ?= default

.PHONY: help install up down nuke lint fmt test all ci ci-eval fixture

help:
	@echo "install  uv sync (exact versions from uv.lock)"
	@echo "up/down  start/stop Postgres+pgvector;  nuke  also deletes the DB volume"
	@echo "lint     ruff check + format check;  fmt  apply formatting"
	@echo "test     pytest"
	@echo "all      full pipeline (PROFILE=default|ci)"
	@echo "ci       lint + test + pipeline + ci-eval on the ci profile"
	@echo "ci-eval  rewrite, answer, grade and report on the ci profile (fake LLM, \$$0)"
	@echo "fixture  regenerate the committed 20-patient CI fixture (needs Java)"

install:
	uv sync --frozen --extra embed

up:
	docker compose up -d --wait

down:
	docker compose down

nuke:
	docker compose down -v

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

all: up
	uv run rwe all --profile $(PROFILE)

ci: lint test
	uv run rwe all --profile ci
	$(MAKE) ci-eval

# The LLM path end to end on the ci profile: fake provider (no key, no network, $0) and
# fake embedder. Exercises batching, caching, grading and the report, not model quality.
ci-eval:
	uv run rwe rewrite --scope test --submit --profile ci
	uv run rwe rewrite --scope test --profile ci
	uv run rwe index --messy --profile ci
	for c in clean messy; do 	  uv run rwe final --corpus $$c --mode hybrid_recency --submit --profile ci && 	  uv run rwe final --corpus $$c --mode hybrid_recency --profile ci || exit 1; 	done
	uv run rwe report --profile ci

fixture:
	uv run rwe fixture
