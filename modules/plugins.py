"""Eklentiler: ~/.jarvis/plugins klasörüne atılan .py dosyaları Jarvis'e yeni komut ekler.

Bir eklenti dosyası şunları tanımlar:
    NAME = "Saat"                      # (isteğe bağlı) arayüzde görünen ad
    DESCRIPTION = "Saati söyler"       # (isteğe bağlı)
    def handle(cmd_lower: str, command: str) -> str | None:
        ...                             # komutu işlerse yanıt metni, işlemezse None
Hatalı bir eklenti diğerlerini ve Jarvis'i bozmaz; hata günlüğe yazılır ve o eklenti atlanır.
Ayarlar/listeleme eklenti kodunu ÇALIŞTIRMAZ: ad, açıklama ve `handle` varlığı kaynak kodundan okunur.
Eklenti modülü yalnız gerçek komut dispatch'inde (`handle`) yürütülür.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import ast
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


def _static_info(path) -> dict:
    """Ayarlar'ın gösterdiği alanları kaynak kodundan okur; eklenti modülünü import etmez ve yürütmez."""
    name, description, has_handle, error = path.stem, "", False, ""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.warning("Eklenti okunamadı (%s): %s", path.name, error)
    else:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "handle":
                has_handle = True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ("NAME", "DESCRIPTION"):
                        try:
                            value = ast.literal_eval(node.value)
                        except (ValueError, SyntaxError):
                            continue          # sabit olmayan ad yalnız varsayılan dosya adını kullanır
                        if isinstance(value, str) and target.id == "NAME" and value.strip():
                            name = value
                        elif isinstance(value, str) and target.id == "DESCRIPTION":
                            description = value
    if not error and not has_handle:
        error = "handle(cmd_lower, command) işlevi yok"
    return {"file": path.name, "name": name, "description": description,
            "ok": has_handle and not error, "error": error}


def listing() -> list[dict]:
    return [_static_info(p) for p in sorted(DIR.glob("*.py"))]


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
