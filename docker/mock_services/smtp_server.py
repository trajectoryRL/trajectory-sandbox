"""Lightweight SMTP server for the sandbox.

Agents can send email via standard SMTP (port 1025) using smtplib, curl, etc.
Received messages are stored in the shared ServiceState and appear in /state
alongside HTTP-sent emails.

Usage (inside sandbox container):
    python3 -c "
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText('Body here')
    msg['Subject'] = 'Status update'
    msg['From'] = 'agent@techcorp.com'
    msg['To'] = 'client@bigclient.com'
    with smtplib.SMTP('localhost', 1025) as s:
        s.send_message(msg)
    "
"""

from __future__ import annotations

import asyncio
import email
import logging
import uuid
from datetime import datetime
from email.policy import default as default_policy
from typing import TYPE_CHECKING

from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Message

if TYPE_CHECKING:
    from mock_services.state_store import SQLiteStateStore

logger = logging.getLogger(__name__)


class SandboxSMTPHandler:
    """aiosmtpd handler that stores received messages in SQLiteStateStore."""

    def __init__(self, state: "SQLiteStateStore"):
        self.state = state

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        try:
            msg = email.message_from_bytes(envelope.content, policy=default_policy)
            stored = {
                "id": str(uuid.uuid4()),
                "from": envelope.mail_from or msg.get("From", ""),
                "to": envelope.rcpt_tos or [msg.get("To", "")],
                "subject": msg.get("Subject", ""),
                "body": self._extract_body(msg),
                "timestamp": datetime.utcnow().isoformat(),
                "via": "smtp",
            }
            self.state.append("sent_emails", stored)
            self.state.log_action("email", "smtp_send", stored)
            logger.info("SMTP: received email from %s to %s: %s",
                        stored["from"], stored["to"], stored["subject"])
        except Exception as e:
            logger.error("SMTP handler error: %s", e)
            return f"500 Error: {e}"
        return "250 Message accepted"

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="replace")
            return ""
        payload = msg.get_payload(decode=True)
        return payload.decode(errors="replace") if payload else ""


def start_smtp_server(state: "ServiceState", host: str = "0.0.0.0", port: int = 1025):
    """Start SMTP server in background. Call from the main process."""
    handler = SandboxSMTPHandler(state)
    controller = Controller(handler, hostname=host, port=port)
    controller.start()
    logger.info("SMTP server listening on %s:%d", host, port)
    return controller
