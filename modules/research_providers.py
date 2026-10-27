"""Provider-neutral, read-only research contracts for Phase 4A.

Search and extraction are deliberately separate. Provider adapters only build
validated request descriptions; the runtime injects the network transport and
keeps credentials outside model/context payloads.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from urllib.parse import parse_qs, quote_plus, urlsplit

from modules import public_sources

_SEARCH_PROVIDERS = frozenset({"searxng", "duckduckgo", "tavily", "exa", "arxiv"})
_EXTRACTORS = frozenset({"firecrawl", "public_sources"})


def _query(query: str) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Araştırma sorgusu geçersiz.")
    return query.strip()


def _limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Araştırma sonuç sınırı 1–50 olmalı.")
    return limit


def search_request(query: str, *, provider: str = "searxng", limit: int = 10) -> dict:
    """Build a provider request without executing a network call or exposing keys."""
    query = _query(query)
    limit = _limit(limit)
    if provider not in _SEARCH_PROVIDERS:
        raise ValueError("Arama sağlayıcısı desteklenmiyor.")
    if provider == "searxng":
        return {"provider": provider, "operation": "search", "method": "GET", "path": "/search", "params": {"q": query, "format": "json", "pageno": 1, "limit": limit}}
    if provider == "duckduckgo":
        return {"provider": provider, "operation": "search", "method": "GET", "path": "/html/", "params": {"q": query, "kl": "tr-tr", "limit": limit}}
    if provider == "tavily":
        return {"provider": provider, "operation": "search", "method": "POST", "path": "/search", "json": {"query": query, "max_results": limit, "include_answer": False}}
    if provider == "exa":
        return {"provider": provider, "operation": "search", "method": "POST", "path": "/search", "json": {"query": query, "numResults": limit, "contents": {"text": {"maxCharacters": 4000}}}}
    return {"provider": provider, "operation": "search", "method": "GET", "path": "/api/query", "params": {"search_query": query, "start": 0, "max_results": limit}}



def _duckduckgo_transport(request: dict) -> dict:
    """Read bounded DuckDuckGo HTML and expose only public result URLs."""
    if not isinstance(request, dict) or request.get("provider") != "duckduckgo":
        raise ValueError("Salt-okunur arama taşıyıcısı geçersiz.")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    query = _query(params.get("q"))
    limit = _limit(params.get("limit"))
    response = public_sources.fetch(
        "https://html.duckduckgo.com/html/?q=" + quote_plus(query) + "&kl=tr-tr"
    )
    from bs4 import BeautifulSoup
    page = BeautifulSoup(response["body"].decode("utf-8", errors="replace"), "html.parser")
    results = []
    for link in page.select("a.result__a"):
        href = str(link.get("href") or "").strip()
        title = link.get_text(" ", strip=True)
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlsplit(href)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            href = (parse_qs(parsed.query).get("uddg") or [""])[0]
        try:
            target = public_sources.address(href)
        except ValueError:
            continue
        if not title or any(row["url"] == target for row in results):
            continue
        results.append({"url": target, "title": title[:400], "snippet": ""})
        if len(results) >= limit:
            break
    return {"results": results}


def search_public(query: str) -> list[dict]:
    """Search one keyless public provider through the bounded HTTPS reader."""
    return search_all(query, providers=("duckduckgo",), transport=_duckduckgo_transport)

def extract_request(url: str, *, provider: str = "public_sources") -> dict:
    """Build a separate extraction request; search results never imply article proof."""
    normalized = public_sources.address(url)
    if provider not in _EXTRACTORS:
        raise ValueError("İçerik çıkarma sağlayıcısı desteklenmiyor.")
    return {"provider": provider, "operation": "extract", "method": "POST" if provider == "firecrawl" else "GET", "url": normalized}


def extract_source(url: str, *, fetcher=None) -> dict:
    """Read one public source through the existing bounded HTTPS reader."""
    request = extract_request(url)
    if fetcher is None:
        # Preserve the existing browser reader's bounded, user-flow semantics.
        from modules.browser import page_text
        return {"url": request["url"], "text": page_text(request["url"]), "content_type": ""}
    response = fetcher(request["url"])
    if not isinstance(response, dict) or response.get("url") != request["url"] or not isinstance(response.get("body"), bytes):
        raise ValueError("Kaynak okuyucu geçerli yanıt üretmedi.")
    return {"url": request["url"], "text": public_sources.text(response["body"]), "content_type": response.get("content_type", "")}


def normalize_results(provider: str, payload: dict, *, limit: int = 10) -> list[dict]:
    """Normalize provider payloads into evidence candidates, not verified claims."""
    if provider not in _SEARCH_PROVIDERS or not isinstance(payload, dict):
        raise ValueError("Arama sağlayıcı yanıtı geçersiz.")
    limit = _limit(limit)
    rows = payload.get("results") or payload.get("items") or payload.get("organic_results") or []
    if not isinstance(rows, list):
        raise ValueError("Arama sonuç listesi geçersiz.")
    normalized = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("link")
        title = row.get("title") or row.get("name")
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            continue
        normalized.append({"provider": provider, "title": title.strip()[:400], "url": url.strip(), "snippet": str(row.get("snippet") or row.get("text") or row.get("content") or "")[:4000], "source_kind": "academic" if provider == "arxiv" else "web", "verified": False})
    return normalized


def search_all(query: str, *, providers=("searxng", "duckduckgo", "tavily", "exa"), transport, limit: int = 10) -> list[dict]:
    """Run injected read-only provider transports and normalize their candidates."""
    query = _query(query)
    if not callable(transport):
        raise ValueError("Arama taşıyıcısı callable olmalı.")
    output = []
    for provider in providers:
        request = search_request(query, provider=provider, limit=limit)
        payload = transport(request)
        output.extend(normalize_results(provider, payload, limit=limit))
    return rank_results(output)[:limit]


def rank_results(results: list[dict], *, preferred_kinds=("official", "academic", "web")) -> list[dict]:
    if not isinstance(results, list):
        raise ValueError("Araştırma sonuçları liste olmalı.")
    preference = {kind: len(preferred_kinds) - index for index, kind in enumerate(preferred_kinds)}
    clean = [deepcopy(row) for row in results if isinstance(row, dict) and isinstance(row.get("url"), str) and isinstance(row.get("title"), str)]
    return sorted(clean, key=lambda row: (-preference.get(row.get("source_kind"), 0), -int(bool(row.get("verified"))), row["title"].casefold()))


def _claim_text(value) -> str:
    text = str(value or "").strip().casefold()
    text = text.translate(str.maketrans("çğıöşü", "cgiosu"))
    return re.sub(r"\s+", " ", text)


def _claim_context(row: dict) -> tuple:
    """Return the comparable fact context; different scope/time is not a clash."""
    subject = _claim_text(row.get("subject"))
    claim_type = _claim_text(row.get("claim_type"))
    scope = _claim_text(row.get("scope"))
    observed = str(row.get("observed_at") or row.get("published") or row.get("date") or "").strip()[:10]
    # A bare text claim has no proven subject/time binding. Preserve the legacy
    # conservative comparison; only structured evidence can explain a date gap.
    return (subject, claim_type, scope, observed) if subject or claim_type or scope else ("", "", "", "")


def _claim_value(row: dict) -> tuple[str, str]:
    value = row.get("value")
    unit = _claim_text(row.get("unit"))
    if isinstance(value, bool):
        return ("categorical", str(value).casefold())
    if isinstance(value, (int, float)):
        return ("numeric", format(value, ".15g") + "|" + unit)
    text = _claim_text(value if value is not None else row.get("claim"))
    if not text:
        return ("", "")
    categories = {"approved": "approved", "onaylandi": "approved",
                  "rejected": "rejected", "reddedildi": "rejected"}
    return ("categorical", categories.get(text, text) + "|" + unit)


def _claim_rows(sources: list[dict]) -> list[dict]:
    rows = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        kind, value = _claim_value(source)
        if value:
            rows.append({"index": index, "context": _claim_context(source), "kind": kind,
                         "value": value, "source": deepcopy(source)})
    return rows


def _trusted_verification(source: dict) -> bool:
    return bool(source.get("verified")) or source.get("source_kind") in {"official", "academic"}


def compare_sources(sources: list[dict]) -> dict:
    """Compare structured evidence claims without mistaking wording for conflict."""
    if not isinstance(sources, list) or not sources:
        raise ValueError("Karşılaştırılacak kaynak gerekli.")
    rows = _claim_rows(sources)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["context"], []).append(row)
    conflicts = []
    claim_values = set()
    for context, candidates in grouped.items():
        values = {candidate["value"] for candidate in candidates}
        claim_values.update(values)
        if len(values) > 1:
            conflicts.append({"context": context, "values": sorted(values),
                              "reason_code": "NUMERIC_CONFLICT" if all(candidate["kind"] == "numeric" for candidate in candidates) else "CATEGORICAL_CONFLICT"})
    status = "conflict" if conflicts else "consistent" if rows else "insufficient"
    return {"status": status, "sources": deepcopy(sources), "claim_count": len(claim_values),
            "needs_review": status != "consistent", "conflicts": conflicts}


def verify_conflict(sources: list[dict], *, verifier=None) -> dict:
    """Use at most one injected existing-source verification step for a real conflict."""
    initial = compare_sources(sources)
    if initial["status"] != "conflict":
        return {**initial, "verification_attempted": False}
    attempted = callable(verifier)
    verified = verifier(deepcopy(initial)) if attempted else []
    if isinstance(verified, dict):
        verified = [verified]
    if not isinstance(verified, list):
        verified = []
    combined = deepcopy(sources) + [deepcopy(row) for row in verified if isinstance(row, dict)]
    after = compare_sources(combined)
    rows = _claim_rows(combined)
    resolutions = []
    for conflict in initial["conflicts"]:
        candidates = [row for row in rows if row["context"] == tuple(conflict["context"])]
        counts = {value: sum(row["value"] == value for row in candidates) for value in {row["value"] for row in candidates}}
        winner, count = max(counts.items(), key=lambda pair: (pair[1], pair[0]))
        if count < 2 or list(counts.values()).count(count) != 1:
            break
        winning = next((row for row in candidates if row["value"] == winner and row["index"] >= len(sources) and _trusted_verification(row["source"])), None)
        if winning is None:
            break
        resolutions.append(winning["source"])
    else:
        if resolutions:
            source = resolutions[0]
            return {**after, "status": "resolved_conflict", "needs_review": False,
                    "verification_attempted": attempted, "resolved_value": source.get("value"),
                    "resolved_by": source, "reason_code": "CONFLICT_RESOLVED"}
    return {**after, "status": "unresolved_conflict", "needs_review": True,
            "verification_attempted": attempted, "reason_code": initial["conflicts"][0]["reason_code"],
            "uncertainty": "Kaynaklar çelişiyor; ek doğrulama sonucu kesinleşmedi."}


def attach_conflict_result(output: dict, result: dict) -> dict:
    """Expose conflict status in the normal user-facing research receipt."""
    if not isinstance(output, dict) or not isinstance(result, dict):
        raise ValueError("Araştırma çatışma çıktısı geçersiz.")
    attached = deepcopy(output)
    attached["source_conflict"] = deepcopy(result)
    if result.get("status") == "unresolved_conflict":
        attached["text"] = str(attached.get("text", "")).rstrip()+"\nBelirsizlik: "+result["uncertainty"]
    elif result.get("status") == "resolved_conflict":
        attached["text"] = str(attached.get("text", "")).rstrip()+"\nKaynak doğrulaması: Çelişen bilgi ek kaynakla doğrulandı."
    return attached


def format_citation(result: dict, number: int) -> str:
    if not isinstance(result, dict) or type(number) is not int or number < 1:
        raise ValueError("Kaynak gösterimi geçersiz.")
    return f"[{number}] {result.get('title', 'Başlıksız')} — {result.get('url', '')}"


@dataclass
class ResearchContext:
    max_chars: int = 12000
    _items: list[dict] = field(default_factory=list)
    characters: int = 0

    def __post_init__(self):
        if type(self.max_chars) is not int or not 100 <= self.max_chars <= 200000:
            raise ValueError("Araştırma bağlam sınırı geçersiz.")

    def add(self, item: dict) -> None:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not isinstance(item.get("text"), str):
            raise ValueError("Araştırma kanıtı geçersiz.")
        remaining = max(0, self.max_chars - self.characters)
        copy = deepcopy(item)
        copy["text"] = copy["text"][:remaining]
        if copy["text"]:
            self._items.append(copy)
            self.characters += len(copy["text"])

    def sources(self) -> list[str]:
        return [item["url"] for item in self._items]

    def items(self) -> list[dict]:
        return deepcopy(self._items)


def weekly_research_request(topic: str) -> dict:
    return {"query": _query(topic), "window_days": 7, "cadence": "weekly", "source_policy": "cite-and-compare"}
