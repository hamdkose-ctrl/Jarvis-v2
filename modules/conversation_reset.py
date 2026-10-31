"""Sohbet sıfırlama sınırı: "yeni sohbet" öncesi geçmiş satırları kısa süreli bağlamdan çıkar.

Yalnız bir zaman kesiti tutar (kalıcı geçmiş silinmez). Brain bağlamı (ActiveContext) ve diğer okuyucular
çeviriye bağımlı olmadan bu modülü kullanır; çeviri kaynak çözümü ayrı bir konudur (chat_translation)."""
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


def mark(slug, resets=None, path=None):
    """Bu kullanıcının sohbet sınırını şimdiye koyar (resets/path yalnız eski adların uyumluluğu için)."""
    resets = _resets if resets is None else resets
    path = _reset_file if path is None else path
    with _lock:
        resets[slug] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(resets), encoding="utf-8")
        os.replace(tmp, path)


def recent(slug, rows, resets=None):
    """Sıfırlama kesitinden sonraki satırlar; kesit yoksa hepsi."""
    cutoff = (_resets if resets is None else resets).get(slug, "")
    return [r for r in rows if str(r.get("ts", "")) > cutoff] if cutoff else rows
