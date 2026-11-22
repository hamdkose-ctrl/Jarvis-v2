"""PUBLIC/PRIVATE provenance authority (Provider Routing Policy v1, P0-1).

Single place that decides whether data may be treated as PUBLIC. Rules (all fail closed):

* Default is PRIVATE. Unlabeled, unknown, malformed or forged data is PRIVATE.
* PUBLIC exists only for sources in ``PUBLIC_SOURCE_ALLOWLIST`` and only through ``mark_public``.
  A source can not declare itself PUBLIC: a dict or a hand-built object carrying
  ``"privacy": "PUBLIC"`` is just PRIVATE data.
* PUBLIC is a taint-like label in one direction only: once a context holds anything PRIVATE
  (history, memory, mail, files, calendar, finance, unlabeled tool output) it stays PRIVATE.
  There is no API that lifts PRIVATE back to PUBLIC.
* A new public source becomes PUBLIC only by adding its id to the allowlist here, with a test.

The guarantee is at rule and test level: code inside the process can still reach ``_ISSUER``
(in-process tampering is out of scope); ``dataclasses.replace``, hand-built labels, subclasses,
dicts and pickles can not mint PUBLIC.

A label proves where data came from, not what it contains. Producers must label their output at the
binding point (P0-3), and ``mark_public`` over content that was already PRIVATE (history, memory,
a ``mark_private`` payload) is forbidden by design rule.

Wired end to end (P0-1): the research worker labels the page text it actually read
(``mark_public('public_page_reader' | 'news_pipeline', text)``) and hands that evidence to the
model call; ``smart_router.request_route`` derives the route class from the evidence, so a
PUBLIC claim that the evidence does not support is demoted to PRIVATE. ``llm.research`` uses the
same authority for a whole labelled batch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from modules.diagnostics import record_failure as _record_failure


class RouteClass(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


# Trusted public source ids. Mapping to the code that produces them (bound in P0-3):
#   web_search         -> research_providers.search_public / search_all / search_news_public
#   news_pipeline      -> news_pipeline publisher/public source results
#   public_page_reader -> research_providers.extract_source for a verified public URL
PUBLIC_SOURCE_ALLOWLIST: frozenset[str] = frozenset({
    "web_search",
    "news_pipeline",
    "public_page_reader",
})

_ISSUER = object()


@dataclass(frozen=True)
class Labeled:
    """Payload plus provenance. PUBLIC labels can only be minted by ``mark_public``."""

    payload: Any
    source_id: str
    route: RouteClass
    # Not an __init__ argument: ``Labeled(...)`` and ``dataclasses.replace`` can never carry it,
    # so a genuine PUBLIC label can not be re-created with a different payload.
    _issuer: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.route is RouteClass.PUBLIC:
            raise ValueError("PUBLIC provenance yalnız mark_public ile üretilebilir.")


def mark_public(source_id: str, payload: Any) -> Labeled:
    """Label payload PUBLIC when ``source_id`` is allowlisted; otherwise it stays PRIVATE."""
    if type(source_id) is str and source_id in PUBLIC_SOURCE_ALLOWLIST:
        label = object.__new__(Labeled)  # skips __init__/__post_init__; the only PUBLIC minting path
        for name, value in (("payload", payload), ("source_id", source_id),
                            ("route", RouteClass.PUBLIC), ("_issuer", _ISSUER)):
            object.__setattr__(label, name, value)
        return label
    return Labeled(payload, (source_id if type(source_id) is str else ""), RouteClass.PRIVATE)


def mark_private(source_id: str, payload: Any) -> Labeled:
    return Labeled(payload, (source_id if type(source_id) is str else ""), RouteClass.PRIVATE)


def item_route(item: object) -> RouteClass:
    """Route class of one item; anything that is not a genuine, allowlisted PUBLIC label is PRIVATE."""
    if type(item) is not Labeled:
        return RouteClass.PRIVATE
    if (item.route is RouteClass.PUBLIC and item._issuer is _ISSUER
            and type(item.source_id) is str and item.source_id in PUBLIC_SOURCE_ALLOWLIST):
        return RouteClass.PUBLIC
    return RouteClass.PRIVATE


class RouteContext:
    """Accumulates the items of one request. PRIVATE is sticky; an empty context is PRIVATE."""

    def __init__(self, items: Iterable[object] = ()) -> None:
        self._count = 0
        self._tainted = False
        for item in items:
            self.add(item)

    def add(self, item: object) -> None:
        self._count += 1
        if item_route(item) is not RouteClass.PUBLIC:
            self._tainted = True

    @property
    def route(self) -> RouteClass:
        if self._count == 0 or self._tainted:
            return RouteClass.PRIVATE
        return RouteClass.PUBLIC


def classify(items: Iterable[object]) -> RouteClass:
    """PUBLIC only when every item is a genuine allowlisted PUBLIC label; otherwise PRIVATE."""
    try:
        return RouteContext(items).route
    except Exception:
        _record_failure('modules/privacy_sources.py:classify')
        return RouteClass.PRIVATE
