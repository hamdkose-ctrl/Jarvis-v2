"""Semantic preview presentation for the canonical Brain result.

Echo renders only the ``EchoPreview`` that Understanding already produced. It has
no execution, permission, effect or completion authority, and it never inspects the
user sentence again.
"""
from __future__ import annotations

from typing import Any

TITLE = "Anlaşılan istek"


def describe(entry: Any) -> str | None:
    semantic = getattr(entry, "understanding", None)
    preview = getattr(semantic, "preview", None)
    return preview.text if preview is not None else None


def present(runtime: Any, entry: Any) -> None:
    text = describe(entry)
    if text is None:
        return
    emit = getattr(runtime, "emit", None)
    if not callable(emit):
        return
    emit("activity", TITLE, f"working|Brain|{text}")
