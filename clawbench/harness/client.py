"""
OpenClaw HTTP Client - Communicates with OpenClaw Gateway.
"""

import httpx
from typing import Any


class OpenClawClient:
    """Client for OpenClaw Gateway HTTP API."""

    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=120.0)

    async def chat_async(self, messages: list[dict]) -> dict:
        """Send chat completion request (async)."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json={"messages": messages},
            )
            response.raise_for_status()
            return response.json()

    def chat(self, messages: list[dict]) -> dict:
        """Send chat completion request (sync)."""
        response = self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json={"messages": messages},
        )
        response.raise_for_status()
        return response.json()

    def get_context(self) -> dict:
        """Get current injected context."""
        response = self.client.get(f"{self.base_url}/context")
        if response.status_code == 404:
            return {}
        return response.json()

    def health(self) -> bool:
        """Check if OpenClaw is healthy."""
        try:
            response = self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False


class MockToolsClient:
    """Client for the mock tools server."""

    def __init__(self, base_url: str = "http://localhost:3001"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30.0)

    def set_scenario(self, scenario: str) -> dict:
        """Set the current scenario for fixture loading."""
        response = self.client.post(f"{self.base_url}/set_scenario/{scenario}")
        response.raise_for_status()
        return response.json()

    def get_tool_calls(self) -> list[dict]:
        """Get all tool calls made in current session."""
        response = self.client.get(f"{self.base_url}/tool_calls")
        response.raise_for_status()
        return response.json()["calls"]

    def health(self) -> bool:
        """Check if mock tools server is healthy."""
        try:
            response = self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    def call_tool(self, tool_name: str, args: dict) -> Any:
        """Call a tool directly (for testing)."""
        response = self.client.post(
            f"{self.base_url}/tools/{tool_name}",
            json=args,
        )
        response.raise_for_status()
        return response.json()
