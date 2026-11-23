"""Ekranda ne olduğunu tek parça söyler: ön plandaki pencere + görünen pencereler.

Neden: kullanıcı "ekranda ne var / hangi program açık" diye sorduğunda cevap
modelden geliyordu; model ekranı görmediği için tahmin ediyordu. Oysa bu bilgi
Windows'tan **kesin** okunabiliyor. Bu modül yalnız OKUR: tıklama, yazma veya
pencere değiştirme yok — bu yüzden Core onay kapısına da girmez.

Kullanılan mevcut sahipler (kopya çıkarılmadı, aynı kaynak):
* `system_control._app_windows()` — görünür üst düzey pencereler (başlık, program).
* `system_control._window_api().GetForegroundWindow()` — ön plandaki pencere.
"""
from __future__ import annotations

import os

from modules.diagnostics import record_failure as _record_failure

# Aynı programın onlarca penceresi olabilir; özet tekrara düşmesin.
MAX_LISTED = 8


def _foreground_handle() -> int | None:
    if os.name != "nt":
        return None
    try:
        from modules import system_control
        return int(system_control._window_api().GetForegroundWindow())
    except Exception:
        _record_failure("modules/pc_awareness.py:foreground")
        return None


def snapshot() -> dict:
    """Ekranın şu anki durumu: ön plan, görünen pencereler, ekran ölçüsü.

    Windows dışında ya da okuma başarısız olursa boş yapı döner; çağıran
    "bilmiyorum" diyebilsin diye hata yutulmaz ama tur da düşürülmez.
    """
    state: dict = {"foreground": None, "windows": [], "screen": None, "platform": os.name}
    if os.name != "nt":
        return state
    try:
        from modules import system_control
        windows = system_control._app_windows()
    except Exception:
        _record_failure("modules/pc_awareness.py:windows")
        return state
    foreground = _foreground_handle()
    rows = [{"hwnd": hwnd, "title": title, "app": app} for hwnd, title, app in windows]
    for row in rows:
        if foreground is not None and row["hwnd"] == foreground:
            state["foreground"] = row
            break
    state["windows"] = rows
    try:
        import pyautogui
        width, height = pyautogui.size()
        state["screen"] = {"width": int(width), "height": int(height)}
    except Exception:
        _record_failure("modules/pc_awareness.py:screen_size")
    return state


def _clean_title(title: str) -> str:
    """Uzun başlıkları kısalt; tırnak içindeki uygulama adını koru."""
    text = " ".join(str(title or "").split())
    return text if len(text) <= 70 else text[:69] + "…"


def summary(state: dict | None = None) -> str:
    """Tek cümlelik, seslenebilir özet. Bilinmeyen durumda dürüst cevap."""
    state = snapshot() if state is None else state
    foreground = state.get("foreground")
    windows = state.get("windows") or []
    if not windows and not foreground:
        return "Ekranı okuyamadım; pencere bilgisi şu an gelmiyor."
    parts = []
    if foreground:
        parts.append(f"Önde {foreground['app']} açık: “{_clean_title(foreground['title'])}”.")
    app_counts: dict[str, int] = {}
    for row in windows:
        app_counts[row["app"]] = app_counts.get(row["app"], 0) + 1
    if app_counts:
        ordered = sorted(app_counts.items(), key=lambda item: (-item[1], item[0]))
        shown = ", ".join(
            f"{app} ({count} pencere)" if count > 1 else app
            for app, count in ordered[:MAX_LISTED])
        extra = len(ordered) - MAX_LISTED
        parts.append(f"Açık programlar: {shown}" + (f" ve {extra} tane daha." if extra > 0 else "."))
    screen = state.get("screen")
    if screen:
        parts.append(f"Ekran {screen['width']}×{screen['height']}.")
    return " ".join(parts)


def titles(state: dict | None = None) -> list[str]:
    """Görünen pencerelerin başlıkları (ön plandaki ilk sırada)."""
    state = snapshot() if state is None else state
    rows = list(state.get("windows") or [])
    foreground = state.get("foreground")
    if foreground:
        rows.sort(key=lambda row: 0 if row["hwnd"] == foreground["hwnd"] else 1)
    return [_clean_title(row["title"]) for row in rows]


# --- 2. dilim: hedef pencereyi bul ve içini oku (yine yalnız okuma) -------

MAX_CONTROLS = 40
MAX_LISTED_CONTROLS = 12

# Şifre alanı: içeriği ASLA okunmaz, yalnız varlığı söylenir.
_SECRET_HINTS = ("password", "şifre", "sifre", "parola", "pin")

# UIA kontrol türleri İngilizce gelir; seslenebilir Türkçe karşılığı kullanılır.
_KIND_TR = {
    "controltype.button": "düğme", "controltype.menuitem": "menü",
    "controltype.edit": "metin alanı", "controltype.document": "belge",
    "controltype.text": "yazı", "controltype.tabitem": "sekme",
    "controltype.list": "liste", "controltype.listitem": "liste öğesi",
    "controltype.checkbox": "onay kutusu", "controltype.radiobutton": "seçenek",
    "controltype.combobox": "açılır liste", "controltype.window": "pencere",
    "controltype.pane": "bölme", "controltype.toolbar": "araç çubuğu",
    "controltype.image": "görsel", "controltype.hyperlink": "bağlantı",
    "controltype.slider": "kaydırıcı", "controltype.tree": "ağaç",
    "controltype.treeitem": "ağaç öğesi", "controltype.datagrid": "tablo",
}


def _kind_label(kind: str) -> str:
    """UIA tür adını Türkçeleştirir; tanınmayan tür olduğu gibi kalır."""
    text = str(kind or "").strip()
    return _KIND_TR.get(text.casefold(), text or "öğe")


def find_window(query: str, windows: list[dict] | None = None) -> dict:
    """Ada göre pencere bulur: {'match': tek pencere | None, 'candidates': [...], 'query': ...}.

    Tahmin yok: birden fazla eşleşme varsa `match` None kalır ve çağıran tek
    soru sorar. Ad verilmediyse (`query` boş) öndeki pencere döner.
    """
    rows = list(windows if windows is not None else snapshot()["windows"])
    text = " ".join(str(query or "").split()).casefold()
    if not text:
        foreground = (snapshot() if windows is None else {}).get("foreground")
        return {"match": foreground, "candidates": [], "query": text, "reason": "foreground"}
    def _fold(value: str) -> str:
        table = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")
        return " ".join(str(value or "").casefold().translate(table).split())
    needle = _fold(text)
    # Türkçe iyelik/hâl ekleri: "not defterinin", "chrome'un" → "not defteri", "chrome".
    variants = [needle]
    for suffix in ("nin", "nun", "nın", "nün", "in", "un", "ın", "ün", "si", "sı"):
        if needle.endswith(suffix) and len(needle) - len(suffix) >= 3:
            variants.append(needle[: -len(suffix)].strip())
    hits: list[dict] = []
    for candidate in variants:
        hits = [row for row in rows
                if candidate in _fold(row.get("title")) or candidate in _fold(row.get("app"))]
        if hits:
            break
    if len(hits) == 1:
        return {"match": hits[0], "candidates": [], "query": text, "reason": "unique"}
    if len(hits) > 1:
        return {"match": None, "candidates": hits, "query": text, "reason": "ambiguous"}
    return {"match": None, "candidates": [], "query": text, "reason": "missing"}


def _secret(control: dict) -> bool:
    label = str(control.get("name") or control.get("label") or "").casefold()
    kind = str(control.get("type") or control.get("role") or "").casefold()
    return "edit" in kind or "text" in kind and any(hint in label for hint in _SECRET_HINTS)


def controls(window: dict) -> dict:
    """Pencerenin okunabilen kontrolleri (yalnız okuma, pencere öne getirilmez)."""
    title = str(window.get("title") or "")
    try:
        from modules.desktop_uia import DesktopUI
        observed = DesktopUI().observe(title, hwnd=window.get("hwnd"))
    except Exception as exc:
        _record_failure("modules/pc_awareness.py:controls")
        return {"title": title, "controls": [], "error": type(exc).__name__}
    raw = list(observed.get("controls") or [])
    cleaned, seen = [], set()
    for row in raw[:MAX_CONTROLS]:
        if not isinstance(row, dict):
            continue
        name = " ".join(str(row.get("name") or row.get("label") or "").split())
        kind = str(row.get("type") or row.get("role") or "öğe")
        if not name:
            continue
        key = (kind, name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"name": name[:60], "type": kind, "secret": _secret(row)})
    return {"title": observed.get("title") or title, "app": observed.get("app"),
            "controls": cleaned, "error": None, "total": len(raw)}


def describe_controls(result: dict) -> str:
    """Kontrol listesini tek paragraflık, seslenebilir Türkçe özete çevirir."""
    title = _clean_title(result.get("title") or "")
    if result.get("error"):
        return (f"“{title}” penceresini okuyamadım; yönetici yetkisi gerekiyor olabilir.")
    rows = result.get("controls") or []
    if not rows:
        return f"“{title}” penceresinde okunabilen bir düğme ya da alan göremiyorum."
    groups: dict[str, list[str]] = {}
    secret_note = False
    for row in rows:
        if row.get("secret"):
            secret_note = True
        groups.setdefault(_kind_label(str(row.get("type") or "")), []).append(row["name"])
    parts = []
    for kind, names in list(groups.items())[:6]:
        shown = "; ".join(names[:MAX_LISTED_CONTROLS])
        extra = len(names) - MAX_LISTED_CONTROLS
        parts.append(f"{kind}: {shown}" + (f" (+{extra})" if extra > 0 else ""))
    text = f"“{title}” penceresinde {len(rows)} okunabilir öğe var. " + " | ".join(parts)
    if secret_note:
        text += " Şifre alanı var; içeriğini okumuyorum."
    return text


def describe_window(query: str = "") -> dict:
    """Soruya göre pencereyi bulup özetler: {'text': ..., 'reason': ..., 'candidates': ...}."""
    found = find_window(query)
    if found["reason"] == "ambiguous":
        names = "; ".join(_clean_title(row["title"]) for row in found["candidates"][:5])
        return {"text": f"Birden fazla pencere eşleşti: {names}. Hangisini okuyayım?",
                "reason": "ambiguous", "candidates": found["candidates"]}
    if found["reason"] == "missing":
        return {"text": f"Açık bir “{query}” penceresi göremiyorum.", "reason": "missing",
                "candidates": []}
    window = found["match"]
    if not window:
        return {"text": "Hangi pencereyi okuyacağımı bilmiyorum; adını söyler misin?",
                "reason": "missing", "candidates": []}
    result = controls(window)
    prefix = "Öndeki pencereyi okudum. " if found["reason"] == "foreground" else ""
    return {"text": prefix + describe_controls(result), "reason": found["reason"],
            "candidates": [], "window": window}
