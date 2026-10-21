"""Sealed RSS/API news receipts. Discovery provenance stays outside the model."""
from __future__ import annotations

import hashlib
from datetime import date
from urllib.parse import urlsplit

from modules import public_sources


PROVIDERS = (
    {
        "id": "trt_haber",
        "name": "TRT Haber",
        "publisher": "trthaber.com",
        "kind": "rss",
        "endpoint": "https://www.trthaber.com/guncel_articles.rss",
    },
    {
        "id": "aa_teyit",
        "name": "Anadolu Ajansı",
        "publisher": "aa.com.tr",
        "kind": "rss",
        "endpoint": "https://www.aa.com.tr/tr/teyithatti/rss/news?cat=0",
    },
)

_REQUIRED = {"provider_id", "publisher", "url", "title", "published", "summary", "source_summary", "seal"}


def providers() -> list[dict]:
    return [dict(row) for row in PROVIDERS]


def _provider(provider_id: str) -> dict:
    for row in PROVIDERS:
        if row["id"] == provider_id:
            return row
    raise ValueError("Kayıtlı RSS/API sağlayıcısı bulunamadı.")


def _publisher_from_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    labels = host.split(".")
    return ".".join(labels[-3:] if ".".join(labels[-2:]) in {"com.tr", "org.tr", "gov.tr", "edu.tr"} else labels[-2:])


def seal(provider_id: str, *, url: str, title: str, published: str, summary: str, source_summary: str) -> dict:
    provider = _provider(provider_id)
    canonical = public_sources.address(url)
    if _publisher_from_url(canonical) != provider["publisher"]:
        raise ValueError("Makbuz bağlantısı kayıtlı yayıncıyla eşleşmiyor.")
    title = " ".join(str(title).split())
    summary = " ".join(str(summary).split())
    source_summary = " ".join(str(source_summary).split())
    if not title or not summary or not source_summary:
        raise ValueError("Makbuz başlık ve özet alanları boş olamaz.")
    day = date.fromisoformat(str(published)).isoformat()
    raw = "\n".join((provider_id, canonical, title, day, summary, source_summary))
    token = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "provider_id": provider_id,
        "publisher": provider["publisher"],
        "url": canonical,
        "title": title,
        "published": day,
        "summary": summary,
        "source_summary": source_summary,
        "seal": token,
    }


def validate(receipt: dict) -> dict:
    if not isinstance(receipt, dict) or set(receipt) != _REQUIRED:
        raise ValueError("Mühürlü haber makbuzu alanları eksik veya fazla.")
    expected = seal(
        receipt["provider_id"],
        url=receipt["url"],
        title=receipt["title"],
        published=receipt["published"],
        summary=receipt["summary"],
        source_summary=receipt["source_summary"],
    )
    if expected["seal"] != receipt["seal"]:
        raise ValueError("Haber makbuzu mührü doğrulanamadı.")
    return dict(receipt)


def article_date(article: dict, receipt: dict) -> str:
    """Use page date when present; only fall back to the sealed same-URL feed date."""
    receipt = validate(receipt)
    if public_sources.address(article.get("url", "")) != receipt["url"]:
        raise ValueError("RSS/API tarihi farklı bir haber bağlantısına taşınamaz.")
    page_day = article.get("published")
    if page_day:
        page_day = date.fromisoformat(str(page_day)).isoformat()
        if page_day != receipt["published"]:
            raise ValueError("Sayfa tarihi ile mühürlü RSS/API tarihi çelişiyor.")
        return page_day
    return receipt["published"]


def require_two_publishers(receipts: list[dict]) -> list[dict]:
    valid = [validate(row) for row in receipts]
    publishers = {row["publisher"] for row in valid}
    if len(valid) < 2 or len(publishers) < 2:
        raise ValueError("Hedefi kapatmak için iki ayrı yayıncıdan iki geçerli mühürlü makbuz gerekli.")
    return valid


def model_payload(receipts: list[dict]) -> list[dict]:
    """The model may summarize verified receipts; it does not choose providers or invent dates."""
    return [
        {
            "url": row["url"],
            "title": row["title"],
            "published": row["published"],
            "summary": row["summary"],
            "source_summary": row["source_summary"],
            "publisher": row["publisher"],
        }
        for row in require_two_publishers(receipts)
    ]
