.PHONY: install build test test-unit test-docker test-agent-judge clean

SANDBOX_IMAGE    := ghcr.io/trajectoryrl/trajrl-bench:latest
HERMES_IMAGE     := ghcr.io/trajectoryrl/hermes-agent:latest
CLAUDECODE_IMAGE := ghcr.io/trajectoryrl/claude-code-agent:latest
OPENCLAW_IMAGE   := ghcr.io/trajectoryrl/openclaw-agent:latest

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:
	pip install -e ".[dev]"

build:
	docker build -f docker/Dockerfile.sandbox    -t $(SANDBOX_IMAGE) .
	docker build -f docker/Dockerfile.hermes     -t $(HERMES_IMAGE) .
	docker build -f docker/Dockerfile.claudecode -t $(CLAUDECODE_IMAGE) .
	docker build -f docker/Dockerfile.openclaw   -t $(OPENCLAW_IMAGE) .

build-sandbox:
	docker build -f docker/Dockerfile.sandbox    -t $(SANDBOX_IMAGE) .

build-hermes:
	docker build -f docker/Dockerfile.hermes     -t $(HERMES_IMAGE) .

build-claudecode:
	docker build -f docker/Dockerfile.claudecode -t $(CLAUDECODE_IMAGE) .

build-openclaw:
	docker build -f docker/Dockerfile.openclaw   -t $(OPENCLAW_IMAGE) .

# ---------------------------------------------------------------------------
# Tests (ordered by what they need)
# ---------------------------------------------------------------------------

# No Docker, no API key — scoring math, fixtures, CLI scenario files.
test-unit:
	pytest tests/ -v \
		--ignore=tests/test_e2e_docker.py \
		--ignore=tests/test_integration.py \
		--ignore=tests/test_agent_judge_live.py

# Needs Docker + sandbox image built
test-docker:
	python tests/test_e2e_docker.py

# Needs Docker + sandbox + hermes + LLM_API_KEY in .env.
# The canonical integration test: three-container agent-judge flow.
test-agent-judge:
	python tests/test_agent_judge_live.py

# All offline tests
test: test-unit

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info trajrl_bench/__pycache__ tests/__pycache__
	docker rm -f sandbox_ajt testee_ajt judge_ajt 2>/dev/null || true
	docker network rm agent_judge_live_test 2>/dev/null || true
