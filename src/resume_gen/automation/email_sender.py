"""Send an application email with resume + cover letter attached, via SMTP.

Phase-3 scaffold: functional SMTP sender, off by default. Configure SMTP_* in
.env. For Gmail, use an App Password (not your account password)."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
    *,
    dry_run: bool = True,
) -> dict:
    """Send (or, by default, dry-run preview) an application email."""
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("FROM_EMAIL", user)

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for att in attachments or []:
        att = Path(att)
        data = att.read_bytes()
        subtype = "pdf" if att.suffix.lower() == ".pdf" else "octet-stream"
        msg.add_attachment(data, maintype="application", subtype=subtype, filename=att.name)

    if dry_run:
        return {"dry_run": True, "to": to, "subject": subject,
                "attachments": [a.name for a in (attachments or [])]}

    if not host:
        raise RuntimeError("SMTP_HOST not configured; cannot send. Set SMTP_* in .env.")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        if user:
            s.login(user, password)
        s.send_message(msg)
    return {"sent": True, "to": to, "subject": subject}
