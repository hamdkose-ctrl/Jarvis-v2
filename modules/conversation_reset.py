"""Sohbet sıfırlama sınırı: "yeni sohbet" öncesi geçmiş satırları kısa süreli bağlamdan çıkar.

Yalnız bir zaman kesiti tutar (kalıcı geçmiş silinmez). Brain bağlamı (ActiveContext) ve diğer
okuyucular bu modülü doğrudan kullanır; çeviri kaynak seçimi yalnız canonical Reference
Resolver'a aittir."""
import json
import os
import threading
from datetime import datetime

from config import DATA_DIR

_lock = threading.RLock()
_reset_file = DATA_DIR / "chat_sessions.json"
try:
    _resets = json.loads(_reset_file.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _resets = {}


def mark(slug):
    """Bu kullanıcının sohbet sınırını şimdiye koyar."""
    with _lock:
        _resets[slug] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        tmp = _reset_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(_resets), encoding="utf-8")
        os.replace(tmp, _reset_file)


def recent(slug, rows):
    """Sıfırlama kesitinden sonraki satırlar; kesit yoksa hepsi."""
    cutoff = _resets.get(slug, "")
    return [r for r in rows if str(r.get("ts", "")) > cutoff] if cutoff else rows
