#!/usr/bin/env python3
"""
Test mock tools server manually.

Usage:
    python scripts/test_mock_tools.py
"""

import httpx
import json

BASE_URL = "http://localhost:3001"


def test_health():
    print("Testing health endpoint...")
    r = httpx.get(f"{BASE_URL}/health")
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    return r.status_code == 200


def test_set_scenario(scenario: str = "inbox_triage"):
    print(f"\nSetting scenario to: {scenario}")
    r = httpx.post(f"{BASE_URL}/set_scenario/{scenario}")
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    return r.status_code == 200


def test_list_tools():
    print("\nListing available tools...")
    r = httpx.get(f"{BASE_URL}/tools")
    tools = r.json()["tools"]
    print(f"  Found {len(tools)} tools:")
    for tool in tools:
        print(f"    - {tool['name']}: {tool['description'][:50]}...")
    return True


def test_inbox_list():
    print("\nTesting inbox.list...")
    r = httpx.post(f"{BASE_URL}/tools/inbox.list", json={})
    print(f"  Status: {r.status_code}")
    messages = r.json()["messages"]
    print(f"  Found {len(messages)} messages:")
    for msg in messages:
        urgent = "[URGENT]" if msg.get("is_urgent") else ""
        print(f"    - {urgent} {msg['sender']}: {msg['subject'][:40]}...")
    return r.status_code == 200


def test_email_draft():
    print("\nTesting email.draft...")
    r = httpx.post(
        f"{BASE_URL}/tools/email.draft",
        json={
            "message_id": "msg_001",
            "instructions": "Thank them and say I'll review by EOD",
        },
    )
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    return r.status_code == 200


def test_get_tool_calls():
    print("\nGetting tool call log...")
    r = httpx.get(f"{BASE_URL}/tool_calls")
    calls = r.json()["calls"]
    print(f"  Found {len(calls)} tool calls:")
    for call in calls:
        print(f"    - {call['ts']}: {call['tool']}")
    return True


def main():
    print("=" * 60)
    print("Mock Tools Server Test")
    print("=" * 60)
    
    all_passed = True
    
    if not test_health():
        print("\n[ERROR] Server not running. Start with:")
        print("  python scripts/run_mock_server.py")
        return
    
    test_set_scenario()
    test_list_tools()
    test_inbox_list()
    test_email_draft()
    test_get_tool_calls()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
