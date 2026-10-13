"""JARVIS bağımlılıklarını çalışan sanal ortamdan kilitler.

Amaç: Ev ve İş bilgisayarlarının aynı Python paket sürümlerini kurması.
`requirements.lock.txt` yalnız kullanıcının çalışan .venv ortamından üretilir; tahmini sürüm yazılmaz.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock.txt"


def in_venv() -> bool:
    return bool(getattr(sys, "base_prefix", sys.prefix) != sys.prefix or hasattr(sys, "real_prefix"))


def create_lock() -> dict:
    """Aktif JARVIS .venv içindeki tam paket sürümlerini requirements.lock.txt dosyasına yazar."""
    if not in_venv():
        raise RuntimeError("Paket sürümleri yalnız JARVIS .venv içinden sabitlenebilir. JARVIS'i baslat.bat ile açıp yeniden dene.")
    cp = subprocess.run([sys.executable, "-m", "pip", "freeze"], cwd=ROOT, capture_output=True,
                        text=True, timeout=90)
    if cp.returncode:
        detail = (cp.stderr or cp.stdout or "pip freeze başarısız").strip().splitlines()[-1]
        raise RuntimeError("Paket sürümleri okunamadı: " + detail[:260])
    lines = sorted({x.strip() for x in cp.stdout.splitlines() if x.strip() and not x.lstrip().startswith("#")},
                   key=str.casefold)
    if len(lines) < 5:
        raise RuntimeError("Çalışan ortamdan yeterli paket bilgisi alınamadı; lock dosyası değiştirilmedi.")
    text = ("# JARVIS bağımlılık kilidi\n"
            "# Bu dosya çalışan JARVIS .venv ortamından otomatik üretildi. Elle sürüm tahmini yapmayın.\n"
            "# Ev/İş kurulumunda kurulum.bat bu dosya varsa onu kullanır.\n\n" + "\n".join(lines) + "\n")
    tmp = LOCK.with_suffix(".txt.yeni")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(LOCK)
    return {"path": str(LOCK), "count": len(lines)}


def status() -> dict:
    return {"exists": LOCK.exists(), "path": str(LOCK),
            "count": sum(1 for x in LOCK.read_text(encoding="utf-8").splitlines() if x and not x.startswith("#")) if LOCK.exists() else 0}
