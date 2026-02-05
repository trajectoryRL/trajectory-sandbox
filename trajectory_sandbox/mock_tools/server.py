"""
Mock Tool Server - Serves deterministic tool responses from fixtures.

This server exposes tools that OpenClaw can call. Responses are read from
fixture files to ensure reproducibility.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Mock Tools Server")

FIXTURES_PATH = Path(os.getenv("FIXTURES_PATH", "./fixtures"))
LOG_PATH = Path(os.getenv("LOG_PATH", "./logs"))
CURRENT_SCENARIO = os.getenv("SCENARIO", "inbox_triage")

# Ensure log directory exists
LOG_PATH.mkdir(parents=True, exist_ok=True)

# Tool call log
tool_calls: list[dict] = []


def load_fixture(scenario: str, filename: str) -> Any:
    """Load a fixture file for the current scenario."""
    path = FIXTURES_PATH / scenario / filename
    if not path.exists():
        raise HTTPException(404, f"Fixture not found: {path}")
    with open(path) as f:
        return json.load(f)


def log_tool_call(tool: str, args: dict, result: Any):
    """Log a tool call for later analysis."""
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "tool": tool,
        "args": args,
        "result_summary": str(result)[:200],
    }
    tool_calls.append(entry)
    
    # Also write to file
    log_file = LOG_PATH / f"{CURRENT_SCENARIO}_calls.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# =============================================================================
# Tool Models
# =============================================================================

class InboxListResponse(BaseModel):
    messages: list[dict]


class EmailDraftRequest(BaseModel):
    message_id: str
    instructions: str


class EmailDraftResponse(BaseModel):
    draft_id: str
    preview: str


class EmailSendRequest(BaseModel):
    draft_id: str


class EmailSendResponse(BaseModel):
    status: str
    draft_id: str


class CalendarReadRequest(BaseModel):
    start_date: str | None = None
    end_date: str | None = None


class CalendarReadResponse(BaseModel):
    events: list[dict]


class MemoryReadRequest(BaseModel):
    path: str


class MemoryReadResponse(BaseModel):
    content: str | None
    exists: bool


class MemoryWriteRequest(BaseModel):
    path: str
    content: str


class MemoryWriteResponse(BaseModel):
    success: bool


# =============================================================================
# Tool Endpoints
# =============================================================================

@app.get("/health")
async def health():
    return {"status": "ok", "scenario": CURRENT_SCENARIO}


@app.post("/set_scenario/{scenario}")
async def set_scenario(scenario: str):
    """Set the current scenario (for fixture loading)."""
    global CURRENT_SCENARIO
    CURRENT_SCENARIO = scenario
    tool_calls.clear()
    return {"scenario": CURRENT_SCENARIO}


@app.get("/tool_calls")
async def get_tool_calls():
    """Get all tool calls made in current session."""
    return {"calls": tool_calls}


@app.post("/tools/inbox.list", response_model=InboxListResponse)
async def inbox_list():
    """List inbox messages."""
    inbox = load_fixture(CURRENT_SCENARIO, "inbox.json")
    
    messages = [
        {
            "id": msg["id"],
            "sender": msg["sender"],
            "subject": msg["subject"],
            "snippet": msg.get("body", "")[:100],
            "received_ts": msg.get("received_ts", ""),
            "labels": msg.get("labels", []),
            "is_urgent": msg.get("is_urgent", False),
        }
        for msg in inbox
    ]
    
    log_tool_call("inbox.list", {}, {"count": len(messages)})
    return InboxListResponse(messages=messages)


@app.post("/tools/email.draft", response_model=EmailDraftResponse)
async def email_draft(req: EmailDraftRequest):
    """Draft a reply to an email."""
    draft_id = f"draft_{req.message_id}"
    preview = f"[Draft reply to {req.message_id}]: {req.instructions[:100]}..."
    
    log_tool_call("email.draft", req.model_dump(), {"draft_id": draft_id})
    return EmailDraftResponse(draft_id=draft_id, preview=preview)


@app.post("/tools/email.send", response_model=EmailSendResponse)
async def email_send(req: EmailSendRequest):
    """Send a drafted email. IRREVERSIBLE - requires approval."""
    log_tool_call("email.send", req.model_dump(), {"status": "sent"})
    return EmailSendResponse(status="sent", draft_id=req.draft_id)


@app.post("/tools/calendar.read", response_model=CalendarReadResponse)
async def calendar_read(req: CalendarReadRequest):
    """Read calendar events."""
    try:
        calendar = load_fixture(CURRENT_SCENARIO, "calendar.json")
    except HTTPException:
        calendar = []
    
    # Filter by date range if provided
    events = calendar
    if req.start_date or req.end_date:
        # Simple filtering (in real impl, parse dates properly)
        pass
    
    log_tool_call("calendar.read", req.model_dump(), {"count": len(events)})
    return CalendarReadResponse(events=events)


@app.post("/tools/memory.read", response_model=MemoryReadResponse)
async def memory_read(req: MemoryReadRequest):
    """Read from memory/filesystem."""
    try:
        path = FIXTURES_PATH / CURRENT_SCENARIO / "memory" / req.path
        if path.exists():
            content = path.read_text()
            log_tool_call("memory.read", req.model_dump(), {"exists": True})
            return MemoryReadResponse(content=content, exists=True)
    except Exception:
        pass
    
    log_tool_call("memory.read", req.model_dump(), {"exists": False})
    return MemoryReadResponse(content=None, exists=False)


@app.post("/tools/memory.write", response_model=MemoryWriteResponse)
async def memory_write(req: MemoryWriteRequest):
    """Write to memory/filesystem."""
    # In mock mode, we just log but don't actually write
    log_tool_call("memory.write", req.model_dump(), {"success": True})
    return MemoryWriteResponse(success=True)


# =============================================================================
# MCP-style tool listing (for OpenClaw discovery)
# =============================================================================

@app.get("/tools")
async def list_tools():
    """List available tools in MCP-compatible format."""
    return {
        "tools": [
            {
                "name": "inbox.list",
                "description": "List inbox messages with id, sender, subject, snippet",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "email.draft",
                "description": "Draft a reply to an email",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "ID of email to reply to"},
                        "instructions": {"type": "string", "description": "Instructions for the draft"},
                    },
                    "required": ["message_id", "instructions"],
                },
            },
            {
                "name": "email.send",
                "description": "Send a drafted email. IRREVERSIBLE - requires user approval first!",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string", "description": "ID of draft to send"},
                    },
                    "required": ["draft_id"],
                },
            },
            {
                "name": "calendar.read",
                "description": "Read calendar events",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                        "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    },
                },
            },
            {
                "name": "memory.read",
                "description": "Read a file from memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to read"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "memory.write",
                "description": "Write a file to memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
