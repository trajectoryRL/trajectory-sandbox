.PHONY: install build build-scenario test clean

SANDBOX_AGENT_IMAGE := ghcr.io/trajectoryrl/sandbox-agent:latest

install:
	uv sync

# Build the sandbox-agent image. The per-scenario environment images
# (ghcr.io/trajectoryrl/scenario-<name>) are built on demand via
# `make build-scenario SCENARIO=<name>`.
build:
	docker build -f docker/Dockerfile.sandbox-agent -t $(SANDBOX_AGENT_IMAGE) .

build-scenario:
	@if [ -z "$(SCENARIO)" ]; then \
		echo "Usage: make build-scenario SCENARIO=<name>"; exit 1; \
	fi
	docker build \
		-f scenarios/$(SCENARIO)/environment/Dockerfile \
		-t ghcr.io/trajectoryrl/scenario-$(SCENARIO):latest \
		scenarios/$(SCENARIO)/environment/

test:
	uv run pytest tests/ -v

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info \
	       trajrl_bench/__pycache__ tests/__pycache__
