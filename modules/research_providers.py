"""Provider-neutral, read-only research contracts for Phase 4A.

Search and extraction are deliberately separate. Provider adapters only build
validated request descriptions; the runtime injects the network transport and
keeps credentials outside model/context payloads.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
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


def compare_sources(sources: list[dict]) -> dict:
    if not isinstance(sources, list) or not sources:
        raise ValueError("Karşılaştırılacak kaynak gerekli.")
    claims = {str(row.get("claim", "")).strip() for row in sources if isinstance(row, dict) and str(row.get("claim", "")).strip()}
    status = "conflict" if len(claims) > 1 else "consistent" if claims else "insufficient"
    return {"status": status, "sources": deepcopy(sources), "claim_count": len(claims), "needs_review": status != "consistent"}


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
