from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html import unescape
from pathlib import Path
from typing import Dict, List, Tuple

from .queue import ModerationQueue


MAX_MESSAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ParsedSubmission:
    message_id: str
    sender: str
    subject: str
    body: str
    content_hash: str
    attachments: List[Dict[str, object]]


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def parse_eml(raw_message: bytes) -> ParsedSubmission:
    if len(raw_message) > MAX_MESSAGE_BYTES:
        raise ValueError("email exceeds the 10 MiB intake limit")

    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    message_id = str(message.get("Message-ID", "")).strip()
    if not message_id:
        message_id = "generated:" + hashlib.sha256(raw_message).hexdigest()

    _, sender = parseaddr(str(message.get("From", "")))
    subject = str(message.get("Subject", "")).strip()
    plain_parts: List[str] = []
    html_parts: List[str] = []
    attachments: List[Dict[str, object]] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            attachments.append(
                {
                    "filename": filename or "unnamed-attachment",
                    "content_type": part.get_content_type(),
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            continue

        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain":
            plain_parts.append(text)
        elif part.get_content_type() == "text/html":
            html_parts.append(_html_to_text(text))

    body = "\n\n".join(item.strip() for item in plain_parts if item.strip())
    if not body:
        body = "\n\n".join(item for item in html_parts if item)
    body = body.strip()
    if not body:
        raise ValueError("email does not contain a readable text body")

    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return ParsedSubmission(
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        content_hash=content_hash,
        attachments=attachments,
    )


def ingest_eml(
    raw_message: bytes, database_path: Path
) -> Tuple[ParsedSubmission, str, bool]:
    submission = parse_eml(raw_message)
    queue = ModerationQueue(database_path)
    job_id, created = queue.add_submission(
        message_id=submission.message_id,
        sender=submission.sender,
        subject=submission.subject,
        content_hash=submission.content_hash,
        body=submission.body,
        attachments=submission.attachments,
    )
    return submission, job_id, created
