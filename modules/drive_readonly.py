"""Phase 4D Google Drive, Docs and Sheets read-only adapter."""
from __future__ import annotations

import re
from typing import Any

from config import DATA_DIR

DRIVE_TOKEN = DATA_DIR / "google_drive_readonly_token.json"
DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)
_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{3,200}$")
_RANGE = re.compile(r"^[A-Za-z0-9_ .'-]{1,100}(?:![A-Za-z]{1,3}[1-9][0-9]*(?::[A-Za-z]{1,3}[1-9][0-9]*)?)?$")


class DriveReadonlyError(ValueError):
    pass


def assert_readonly_operation(operation: str) -> None:
    if operation not in {"list", "get", "export", "values.get"}:
        raise DriveReadonlyError("Drive salt-okunur adaptöründe değiştirme işlemi yasaktır.")


def validate_file_id(file_id: str) -> str:
    if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
        raise DriveReadonlyError("Drive dosya kimliği geçersiz.")
    return file_id


def _limit(limit: int, maximum: int) -> int:
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise DriveReadonlyError("Okuma sınırı geçersiz.")
    return limit


def _range(value: str) -> str:
    if not isinstance(value, str) or not _RANGE.fullmatch(value):
        raise DriveReadonlyError("Sheets aralığı geçersiz.")
    return value


def services(*, interactive: bool = False) -> tuple[Any, Any, Any]:
    """Builds read-only API clients with a dedicated, user-owned OAuth token."""
    from googleapiclient.discovery import build
    from modules import google_api

    credentials = google_api._creds(DRIVE_TOKEN, list(DRIVE_SCOPES), interactive)
    return (
        build("drive", "v3", credentials=credentials, cache_discovery=False),
        build("docs", "v1", credentials=credentials, cache_discovery=False),
        build("sheets", "v4", credentials=credentials, cache_discovery=False),
    )


def list_files(drive: Any, *, query: str = "", limit: int = 25) -> list[dict[str, str]]:
    """Metadata-only Drive listing; it never downloads contents."""
    assert_readonly_operation("list")
    limit = _limit(limit, 100)
    if not isinstance(query, str) or len(query) > 500:
        raise DriveReadonlyError("Drive arama ifadesi geçersiz.")
    response = drive.files().list(
        q=query or None,
        pageSize=limit,
        orderBy="modifiedTime desc",
        fields="files(id,name,mimeType,modifiedTime,size)",
    ).execute()
    rows = []
    for item in response.get("files", [])[:limit]:
        if not isinstance(item, dict):
            continue
        file_id, name = item.get("id"), item.get("name")
        if isinstance(file_id, str) and isinstance(name, str):
            rows.append({"id": file_id, "name": name[:500], "mime_type": str(item.get("mimeType", ""))[:200]})
    return rows


def _paragraph_text(document: dict[str, Any], *, limit: int) -> str:
    pieces: list[str] = []
    for part in document.get("body", {}).get("content", []):
        paragraph = part.get("paragraph", {}) if isinstance(part, dict) else {}
        for element in paragraph.get("elements", []) if isinstance(paragraph, dict) else []:
            text = element.get("textRun", {}).get("content", "") if isinstance(element, dict) else ""
            if isinstance(text, str):
                pieces.append(text)
                if sum(map(len, pieces)) >= limit:
                    return "".join(pieces)[:limit].rstrip()
    return "".join(pieces)[:limit].rstrip()


def read_document(docs: Any, document_id: str, *, max_chars: int = 20_000) -> dict[str, str]:
    assert_readonly_operation("get")
    document_id = validate_file_id(document_id)
    _limit(max_chars, 100_000)
    document = docs.documents().get(documentId=document_id).execute()
    title = document.get("title", "") if isinstance(document, dict) else ""
    return {"id": document_id, "title": str(title)[:500], "text": _paragraph_text(document, limit=max_chars)}


def read_sheet(sheets: Any, spreadsheet_id: str, cell_range: str, *, max_rows: int = 500) -> dict[str, Any]:
    assert_readonly_operation("values.get")
    spreadsheet_id = validate_file_id(spreadsheet_id)
    cell_range = _range(cell_range)
    _limit(max_rows, 1_000)
    result = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        majorDimension="ROWS",
    ).execute()
    values = result.get("values", []) if isinstance(result, dict) else []
    safe_rows = [
        [str(value)[:10_000] for value in row[:200]]
        for row in values[:max_rows]
        if isinstance(row, list)
    ]
    return {"id": spreadsheet_id, "range": str(result.get("range", cell_range))[:200], "values": safe_rows}
