"""Eklentiler: ~/.jarvis/plugins klasörüne atılan .py dosyaları Jarvis'e yeni komut ekler.

Bir eklenti dosyası şunları tanımlar:
    NAME = "Saat"                      # (isteğe bağlı) arayüzde görünen ad
    DESCRIPTION = "Saati söyler"       # (isteğe bağlı)
    def handle(cmd_lower: str, command: str) -> str | None:
        ...                             # komutu işlerse yanıt metni, işlemezse None
Hatalı bir eklenti diğerlerini ve Jarvis'i bozmaz; hata günlüğe yazılır ve o eklenti atlanır.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import importlib.util
import logging
from types import ModuleType

from config import DATA_DIR

DIR = DATA_DIR / "plugins"
DIR.mkdir(exist_ok=True)
log = logging.getLogger("jarvis.plugins")
_loaded: dict[str, tuple[float, ModuleType | None, str]] = {}   # dosya -> (mtime, modül, hata)


def _load(path) -> tuple[ModuleType | None, str]:
    mtime = path.stat().st_mtime
    cached = _loaded.get(path.name)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    mod, err = None, ""
    try:
        spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)            # type: ignore[union-attr]
        if not callable(getattr(mod, "handle", None)):
            mod, err = None, "handle(cmd_lower, command) işlevi yok"
    except Exception as e:                       # noqa: BLE001 - eklenti her şeyi fırlatabilir
        _record_failure('modules/plugins.py:_load')
        mod, err = None, f"{type(e).__name__}: {e}"
        log.warning("Eklenti yüklenemedi (%s): %s", path.name, err)
    _loaded[path.name] = (mtime, mod, err)
    return mod, err


def listing() -> list[dict]:
    out = []
    for p in sorted(DIR.glob("*.py")):
        mod, err = _load(p)
        out.append({"file": p.name, "name": getattr(mod, "NAME", p.stem) if mod else p.stem,
                    "description": getattr(mod, "DESCRIPTION", "") if mod else "", "ok": mod is not None, "error": err})
    return out


def handle(command: str, cmd_lower: str) -> str | None:
    for p in sorted(DIR.glob("*.py")):
        mod, _ = _load(p)
        if mod is None:
            continue
        try:
            reply = mod.handle(cmd_lower, command)
        except Exception as e:                   # noqa: BLE001
            _record_failure('modules/plugins.py:handle')
            continue
        if reply:
            return str(reply)
    return None
