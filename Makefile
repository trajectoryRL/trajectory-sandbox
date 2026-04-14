.PHONY: install build test test-unit test-docker test-hermes test-pressure clean

SANDBOX_IMAGE := ghcr.io/trajectoryrl/trajrl-bench:latest
HERMES_IMAGE  := ghcr.io/trajectoryrl/hermes-agent:latest

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:
	pip install -e ".[dev]"

build:
	docker build -f docker/Dockerfile.sandbox -t $(SANDBOX_IMAGE) .
	docker build -f docker/Dockerfile.hermes -t $(HERMES_IMAGE) .

build-sandbox:
	docker build -f docker/Dockerfile.sandbox -t $(SANDBOX_IMAGE) .

build-hermes:
	docker build -f docker/Dockerfile.hermes -t $(HERMES_IMAGE) .

# ---------------------------------------------------------------------------
# Tests (ordered by what they need)
# ---------------------------------------------------------------------------

# No Docker, no API key — just scoring math, fixtures, evidence, judge prompts
test-unit:
	pytest tests/ -v \
		--ignore=tests/test_e2e_docker.py \
		--ignore=tests/test_integration.py \
		--ignore=tests/test_judge_live.py \
		--ignore=tests/test_judge_save.py \
		--ignore=tests/test_skill_vs_baseline.py \
		--ignore=tests/test_hermes_live.py

# Needs Docker + sandbox image built
test-docker:
	python tests/test_e2e_docker.py

# Needs Docker + both images + LLM_API_KEY in .env
test-hermes:
	python tests/test_hermes_live.py

# Needs LLM_API_KEY in .env (no Docker)
test-pressure:
	python tests/test_skill_vs_baseline.py

# All offline tests
test: test-unit

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info trajrl_bench/__pycache__ tests/__pycache__
	docker rm -f sandbox_hermes_test hermes_hermes_test hermes_vol_helper 2>/dev/null || true
	docker network rm hermes_live_test 2>/dev/null || true
