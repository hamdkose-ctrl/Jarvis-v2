"""Yerel dosya işlemleri: listele / oku / aç (yalnız okuma + açma).

Kurallar:
- **Okuma serbest, yazma yok**: bu modül dosya değiştirmez, silmez. Kaydetme ayrı
  modülde (`pc_files`) ve yalnız sandbox'a.
- Listeleme ve okuma **sınırlı**: en çok 50 satır, en çok 200 KB; büyük dosyada
  kesildiğini söyler (sessizce kırpma yok).
- Yalnız kullanıcının ev klasörü altı: `~` dışına çıkan yollar reddedilir.
- `open_file()` yalnız **açar**; içerik değiştirmez, kaydetmez.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure

MAX_ENTRIES = 50
MAX_BYTES = 200_000
HOME = Path.home()
OUTSIDE = "Yalnız ev klasörün altındaki dosyalara bakabiliyorum."
NOT_FOUND = "“{path}” bulunamadı."
LISTED = "{path}: {count} öğe{more}."
READ = "{name} ({size} bayt): {text}{cut}"
OPENED = "“{name}” açıldı."


def _resolve(path: str) -> Path | None:
    try:
        target = Path(os.path.expandvars(str(path or "").strip())).expanduser().resolve()
    except Exception:
        _record_failure("modules/file_ops_local.py:_resolve")
        return None
    # Windows kısa yol adları (HAMDI~1.KOS) ile uzun adlar aynı klasörü gösterir:
    # karşılaştırmayı gerçek yollar üzerinden yap.
    home = Path(os.path.realpath(HOME))
    real = Path(os.path.realpath(target))
    if real != home and home not in real.parents:
        return None
    return target


def list_folder(path: str) -> dict:
    """Klasördeki öğeleri listeler (en çok 50)."""
    target = _resolve(path or str(HOME))
    if target is None:
        return {"status": "refused", "text": OUTSIDE}
    if not target.is_dir():
        return {"status": "missing", "text": NOT_FOUND.format(path=path)}
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except Exception:
        _record_failure("modules/file_ops_local.py:list_folder")
        return {"status": "failed", "text": f"“{target.name}” okunamadı."}
    shown = entries[:MAX_ENTRIES]
    more = "" if len(entries) <= MAX_ENTRIES else f" (ilk {MAX_ENTRIES} tanesi, toplam {len(entries)})"
    names = [f"{e.name}/" if e.is_dir() else e.name for e in shown]
    return {"status": "ok", "text": LISTED.format(path=str(target), count=len(entries), more=more),
            "entries": names}


def read_file(path: str) -> dict:
    """Metin dosyasını okur (200 KB / 50 satır sınırı)."""
    target = _resolve(path)
    if target is None:
        return {"status": "refused", "text": OUTSIDE}
    if not target.is_file():
        return {"status": "missing", "text": NOT_FOUND.format(path=path)}
    try:
        raw = target.read_bytes()[:MAX_BYTES]
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        _record_failure("modules/file_ops_local.py:read_file")
        return {"status": "failed", "text": f"“{target.name}” okunamadı."}
    lines = text.splitlines()
    cut_lines = len(lines) > MAX_ENTRIES
    body = "\n".join(lines[:MAX_ENTRIES])
    cut = "" if not cut_lines and len(raw) < MAX_BYTES else " …(kısaltıldı)"
    return {"status": "ok", "text": READ.format(name=target.name, size=target.stat().st_size, text=body[:1200], cut=cut),
            "content": body}


def open_file(path: str) -> dict:
    """Dosyayı varsayılan uygulamayla açar (içerik değişmez)."""
    target = _resolve(path)
    if target is None:
        return {"status": "refused", "text": OUTSIDE}
    if not target.exists():
        return {"status": "missing", "text": NOT_FOUND.format(path=path)}
    try:
        os.startfile(str(target))          # yalnız Windows
        time.sleep(1.0)
    except Exception:
        _record_failure("modules/file_ops_local.py:open_file")
        return {"status": "failed", "text": f"“{target.name}” açılamadı."}
    return {"status": "done", "text": OPENED.format(name=target.name)}
