"""Remove known obsolete installation files. Personal data is preserved."""
from pathlib import Path
import os
import shutil
ROOT = Path(__file__).resolve().parents[1]
OBSOLETE = (
    "uyandirma_kur.bat", "scripts/uyandirma_kur.bat", "scripts/kur_tarayici.bat",
    "ATOLYEYI_KALDIR.bat", "scripts/atolye_kalintilarini_kaldir.py",
    "modules/selfcoder", "webui/selfcoder_chat.js", "webui/selfcoder_chat.css",
    "tests/test_selfcoder_preview.py", "tests/test_selfcoder_workspace.py", "tests/test_selfcoder_log_regressions.py",
    "tests/fixtures/widget_source.txt", "docs/ATOLYE_ONIZLEME_20261007.md", "docs/GELISTIRME_ATOLYESI.md", "docs/SELF_CODER.md",
    "webui/index.html", "webui/core.js", "webui/cc.js", "webui/pages.js", "webui/pages2.js", "webui/pages3.js",
    "webui/reactor.js", "webui/boot.js", "webui/style.css", "webui/ironman.png", "webui/ring.png",
)
def remove(root=ROOT):
    root=Path(root)
    if not (root/"main.py").is_file() or not (root/"web.py").is_file():
        raise RuntimeError("Jarvis kurulumu bulunamadı; dosya silinmedi.")
    removed=[]
    for rel in OBSOLETE:
        path=root/rel
        if path.is_symlink():path.unlink();removed.append(rel)
        elif path.is_dir():shutil.rmtree(path);removed.append(rel)
        elif path.is_file():path.unlink();removed.append(rel)
    # Only source trees; never walk .venv, Android, personal data, models or skills.
    for base in (root/'modules',root/'tests',root/'scripts',root/'webui'):
        if not base.is_dir() or base.is_symlink():continue
        for current, dirs, files in os.walk(base,topdown=True,followlinks=False):
            for name in list(dirs):
                path=Path(current)/name
                if name=='__pycache__':
                    if path.is_symlink():path.unlink()
                    else:shutil.rmtree(path)
                    removed.append(path.relative_to(root).as_posix());dirs.remove(name)
                elif path.is_symlink() or name in ('.claude','.jarvis','models','skill-observations'):
                    dirs.remove(name)
            for name in files:
                if name.endswith(('.pyc','.pyo')):
                    path=Path(current)/name;path.unlink();removed.append(path.relative_to(root).as_posix())
    for name in ('__pycache__','.ruff_cache','.pytest_cache'):
        path=root/name
        if path.is_symlink():path.unlink();removed.append(name)
        elif path.is_dir():shutil.rmtree(path);removed.append(name)
    for path in root.glob('*.pyc'):
        if path.is_file() or path.is_symlink():path.unlink();removed.append(path.name)
    return removed
if __name__ == "__main__":
    for name in remove():print("Kaldırıldı:",name)

