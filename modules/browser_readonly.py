"""Phase 4C: explicit, model-safe contracts for read-only browser observation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit


class ReadonlyBrowserError(ValueError):
    """A browser request exceeded the read-only observation boundary."""


_FORBIDDEN = frozenset({"click", "fill", "press", "select", "submit", "upload", "login"})
_SECRET_TYPES = frozenset({"password", "hidden", "token"})


def _url(value: str) -> str:
    parsed = urlsplit(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ReadonlyBrowserError("Yalnız geçerli http/https adresi gözlemlenebilir.")
    if parsed.username or parsed.password:
        raise ReadonlyBrowserError("Adres kimlik bilgisi içeremez.")
    return value


def assert_readonly_action(action: dict[str, Any]) -> None:
    if not isinstance(action, dict) or not isinstance(action.get("op"), str):
        raise ReadonlyBrowserError("Tarayıcı eylemi geçersiz.")
    op = action["op"].casefold()
    if op in _FORBIDDEN:
        if op == "upload":
            raise ReadonlyBrowserError("Salt-okunur tarayıcıda yükleme yasaktır.")
        raise ReadonlyBrowserError("Salt-okunur tarayıcıda etkileşimli işlem yasaktır.")
    if op not in {"goto", "read", "accessibility", "tabs", "download_observe", "dialog_observe", "screenshot"}:
        raise ReadonlyBrowserError("Tanımlı olmayan tarayıcı eylemi yasaktır.")


def _field(element: Any, name: str, default: str = "") -> str:
    value = getattr(element, name, default)
    return value if isinstance(value, str) else default


def accessibility_tree(elements: Iterable[Any], *, limit: int = 100) -> list[dict[str, str]]:
    """Return only labels/roles; values of secret-bearing controls never leave the browser."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ReadonlyBrowserError("Erişilebilirlik öğe sınırı geçersiz.")
    tree: list[dict[str, str]] = []
    for element in elements:
        if len(tree) >= limit:
            break
        role = _field(element, "role", "generic")[:80]
        name = _field(element, "name")[:200]
        input_type = _field(element, "input_type").casefold()
        row = {"role": role, "name": name}
        if input_type and input_type not in _SECRET_TYPES:
            row["type"] = input_type[:50]
        tree.append(row)
    return tree


def observe_tabs(pages: Iterable[Any]) -> dict[str, Any]:
    tabs: list[dict[str, Any]] = []
    for page in pages:
        if len(tabs) >= 20:
            break
        url = _url(_field(page, "url"))
        title = _field(page, "title")[:300]
        tabs.append({
            "url": url,
            "title": title,
            "accessibility": accessibility_tree(getattr(page, "elements", ())),
        })
    return {"state": "observed", "tabs": tabs}


def download_receipt(url: str, filename: str, byte_count: int | None = None) -> dict[str, Any]:
    """A download is reported as an observed artifact; this contract never opens it."""
    _url(url)
    name = PurePath(filename).name
    if not name or name != filename or len(name) > 255:
        raise ReadonlyBrowserError("İndirme dosya adı geçersiz.")
    if byte_count is not None and (type(byte_count) is not int or byte_count < 0):
        raise ReadonlyBrowserError("İndirme boyutu geçersiz.")
    return {"state": "observed", "url": url, "filename": name, "bytes": byte_count}


def observe_dialog(dialog: dict[str, Any]) -> dict[str, str]:
    if not isinstance(dialog, dict):
        raise ReadonlyBrowserError("Tarayıcı diyaloğu geçersiz.")
    kind = dialog.get("type")
    message = dialog.get("message", "")
    if not isinstance(kind, str) or not kind.strip() or not isinstance(message, str):
        raise ReadonlyBrowserError("Tarayıcı diyaloğu geçersiz.")
    return {"state": "human_required", "kind": kind[:80], "message": message[:500]}


@dataclass
class CredentialVault:
    """Local vault facade. Encryption/decryption stay in the trusted host, never model payloads."""

    encrypt: Callable[[str], str]
    decrypt: Callable[[str], str]
    _entries: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not callable(self.encrypt) or not callable(self.decrypt):
            raise ReadonlyBrowserError("Yerel kimlik kasası sağlayıcısı geçersiz.")
        if self._entries is None:
            self._entries = {}

    def store(self, label: str, value: str) -> None:
        if not isinstance(label, str) or not label.strip() or not isinstance(value, str) or not value:
            raise ReadonlyBrowserError("Kimlik kasası girdisi geçersiz.")
        self._entries[label] = self.encrypt(value)

    def resolve_for_browser(self, label: str) -> str:
        if label not in self._entries:
            raise ReadonlyBrowserError("Kimlik kasası kaydı bulunamadı.")
        return self.decrypt(self._entries[label])

    def model_safe_metadata(self, label: str) -> dict[str, str]:
        if label not in self._entries:
            raise ReadonlyBrowserError("Kimlik kasası kaydı bulunamadı.")
        return {"label": label, "state": "available_to_trusted_browser_only"}


def two_factor_handoff(account_label: str, prompt: str = "") -> dict[str, str]:
    if not isinstance(account_label, str) or not account_label.strip() or not isinstance(prompt, str):
        raise ReadonlyBrowserError("2FA devri geçersiz.")
    return {"state": "human_required", "account": account_label[:100], "message": prompt[:500]}


class ChromeCDPReadonlyBridge:
    """Adapter boundary for a trusted host's Chrome DevTools connection.

    The caller supplies the CDP connector. This module neither discovers profiles nor
    transmits cookies, passwords, local-storage values, or vault plaintext to a model.
    """

    def __init__(self, connect_over_cdp: Callable[[str], Any]):
        if not callable(connect_over_cdp):
            raise ReadonlyBrowserError("CDP bağlayıcısı geçersiz.")
        self._connect = connect_over_cdp

    def observe(self, endpoint: str) -> dict[str, Any]:
        _url(endpoint)
        browser = self._connect(endpoint)
        contexts = getattr(browser, "contexts", ())
        pages = [page for context in contexts for page in getattr(context, "pages", ())]
        return observe_tabs(pages)
