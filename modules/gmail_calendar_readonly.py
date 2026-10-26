"""Phase 4F: Gmail thread reading and Calendar scheduling suggestions, read-only."""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Iterable

_THREAD_ID = re.compile(r"^[A-Za-z0-9_-]{3,200}$")


class GmailCalendarReadonlyError(ValueError):
    pass


def validate_thread_id(thread_id: str) -> str:
    if not isinstance(thread_id, str) or not _THREAD_ID.fullmatch(thread_id):
        raise GmailCalendarReadonlyError("Gmail konuşma kimliği geçersiz.")
    return thread_id


def _header(message: dict[str, Any], name: str) -> str:
    headers = message.get("payload", {}).get("headers", []) if isinstance(message, dict) else []
    for header in headers:
        if isinstance(header, dict) and header.get("name") == name and isinstance(header.get("value"), str):
            return header["value"][:500]
    return ""


def read_thread(gmail: Any, thread_id: str, *, max_messages: int = 50, max_snippet_chars: int = 1_000) -> dict[str, Any]:
    """Reads a single thread; it cannot label, send, archive, or modify Gmail."""
    thread_id = validate_thread_id(thread_id)
    if type(max_messages) is not int or not 1 <= max_messages <= 100:
        raise GmailCalendarReadonlyError("Konuşma mesaj sınırı geçersiz.")
    if type(max_snippet_chars) is not int or not 1 <= max_snippet_chars <= 5_000:
        raise GmailCalendarReadonlyError("Konuşma metin sınırı geçersiz.")
    payload = gmail.users().threads().get(userId="me", id=thread_id, format="metadata",
        metadataHeaders=["From", "To", "Cc", "Subject", "Date"]).execute()
    messages = []
    for message in payload.get("messages", [])[:max_messages]:
        if not isinstance(message, dict):
            continue
        messages.append({
            "id": str(message.get("id", ""))[:200],
            "from": _header(message, "From"),
            "to": _header(message, "To"),
            "subject": _header(message, "Subject"),
            "date": _header(message, "Date"),
            "snippet": str(message.get("snippet", ""))[:max_snippet_chars],
        })
    return {"id": thread_id, "messages": messages, "truncated": len(payload.get("messages", [])) > len(messages)}


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise GmailCalendarReadonlyError(f"{field} saat dilimi içermeli.")
    return value


def suggest_slot(
    window_start: datetime,
    window_end: datetime,
    busy: Iterable[tuple[datetime, datetime, str]],
    *,
    minutes: int,
) -> dict[str, Any]:
    """Returns one candidate time only; it deliberately never creates or edits an event."""
    start, end = _aware(window_start, "Başlangıç"), _aware(window_end, "Bitiş")
    if end <= start or type(minutes) is not int or not 15 <= minutes <= 480:
        raise GmailCalendarReadonlyError("Planlama aralığı geçersiz.")
    duration = timedelta(minutes=minutes)
    blocked = []
    for row in busy:
        if not isinstance(row, tuple) or len(row) != 3:
            raise GmailCalendarReadonlyError("Takvim meşgul kaydı geçersiz.")
        busy_start, busy_end = _aware(row[0], "Meşgul başlangıcı"), _aware(row[1], "Meşgul bitişi")
        if busy_end <= busy_start:
            raise GmailCalendarReadonlyError("Takvim meşgul aralığı geçersiz.")
        if busy_end > start and busy_start < end:
            blocked.append((max(busy_start, start), min(busy_end, end), str(row[2])[:200]))
    cursor = start
    for busy_start, busy_end, _title in sorted(blocked, key=lambda row: row[0]):
        if cursor + duration <= busy_start:
            return {"state": "suggested", "start": cursor, "end": cursor + duration,
                    "note": "Bu yalnız planlama önerisidir; Jarvis takvime eklemez."}
        if busy_end > cursor:
            cursor = busy_end
    if cursor + duration <= end:
        return {"state": "suggested", "start": cursor, "end": cursor + duration,
                "note": "Bu yalnız planlama önerisidir; Jarvis takvime eklemez."}
    return {"state": "no_slot", "note": "Bu aralıkta yeterli boş zaman bulunamadı; Jarvis takvime eklemez."}
