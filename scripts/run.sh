#!/bin/bash
# Run Trajectory Sandbox
#
# Usage:
#   ./scripts/run.sh [baseline|optimized]
#
# Prerequisites:
#   1. cp .env.example .env
#   2. Edit .env with your API key

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX_DIR="$(dirname "$SCRIPT_DIR")"

cd "$SANDBOX_DIR"

# Check for .env file
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found"
    echo ""
    echo "Create it from the example:"
    echo "  cp .env.example .env"
    echo ""
    echo "Then edit .env and add your API key"
    exit 1
fi

# Source .env to check for API key
set -a
source .env
set +a

if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: No API key set in .env"
    echo ""
    echo "Edit .env and set ANTHROPIC_API_KEY or OPENAI_API_KEY"
    exit 1
fi

# Copy AGENTS.md variant
VARIANT="${1:-baseline}"
if [ "$VARIANT" == "baseline" ]; then
    echo "Using AGENTS.md.baseline"
    cp fixtures/inbox_triage/AGENTS.md.baseline workspace/AGENTS.md
elif [ "$VARIANT" == "optimized" ]; then
    echo "Using AGENTS.md.optimized"
    cp fixtures/inbox_triage/AGENTS.md.optimized workspace/AGENTS.md
else
    echo "Unknown variant: $VARIANT"
    echo "Usage: ./scripts/run.sh [baseline|optimized]"
    exit 1
fi

# Copy USER.md
cp fixtures/inbox_triage/USER.md workspace/USER.md

# Get token from .env or use default
TOKEN="${OPENCLAW_GATEWAY_TOKEN:-sandbox-token-12345}"

echo ""
echo "=============================================="
echo "Starting Trajectory Sandbox"
echo "=============================================="
echo ""
echo "AGENTS.md variant: $VARIANT"
echo ""
echo "Dashboard: http://localhost:18789/?token=${TOKEN}"
echo "Mock tools: http://localhost:3001"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Build and run
docker-compose up --build
