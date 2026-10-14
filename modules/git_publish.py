"""Yerel kaynak değişikliklerini güvenli biçimde ana GitHub dalına yayınlar.

Akış: yerel değişiklik -> test -> uzak dalda çakışma kontrolü -> tek Git commit -> main.
GitHub erişilemezse çalışan yerel sürüm korunur ve sonraki güncelleme tarafından ezilmez.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import base64
import hashlib
import json
import os
import subprocess
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".jarvis" / "selfcoder"
LOCAL = STATE / "local_changes.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _load() -> dict:
    try:
        value = json.loads(LOCAL.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def protect_local(paths: list[str], summary: str) -> None:
    """Henüz GitHub'a ulaşmamış değişiklikleri güncelleyiciye karşı koru."""
    data = _load()
    for rel in sorted(set(paths)):
        p = ROOT / rel
        data[rel] = {"sha256": _sha(p.read_bytes()) if p.exists() else "", "deleted": not p.exists(),
                     "summary": summary[:160], "ts": time.strftime("%Y-%m-%d %H:%M")}
    _save(data)


def forget_local(paths: list[str]) -> None:
    data = _load()
    for rel in paths:
        data.pop(rel, None)
    _save(data)


def local_list() -> dict:
    return _load()


def _api(method: str, path: str, payload: dict | None = None) -> dict:
    import updater
    token = updater._token()  # aynı DPAPI korumalı kimlik bilgisi; diske açık token yazılmaz
    if not token:
        raise RuntimeError("GitHub yazma anahtarı ayarlanmamış")
    url = f"https://api.github.com/repos/{updater.REPO}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Accept":"application/vnd.github+json", "Authorization":f"Bearer {token}",
                 "User-Agent":"jarvis-git-publish", "X-GitHub-Api-Version":"2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw=r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail=""
        try: detail=json.loads(e.read()).get("message", "")
        except Exception: 
            _record_failure('modules/git_publish.py:_api')
            pass
        raise RuntimeError(f"GitHub {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"GitHub bağlantısı kurulamadı: {e.reason}") from e


def _remote_paths(tree_sha: str) -> dict[str, str]:
    tree=_api("GET", f"/git/trees/{tree_sha}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError("GitHub depo ağacı çok büyük; güvenli çakışma kontrolü yapılamadı")
    return {x["path"]:x["sha"] for x in tree.get("tree",[]) if x.get("type")=="blob"}


def publish(paths: list[str], before: dict[str, bytes | None], summary: str) -> str:
    """Test edilmiş dosyaları main'e tek atomik commit olarak gönder; çakışmada asla zorla yazma."""
    import updater
    paths=sorted(set(str(x).replace("\\","/") for x in paths))
    if not paths:
        return "GitHub'a gönderilecek dosya yok."
    ref=_api("GET", f"/git/ref/heads/{updater.BRANCH}")
    head=ref["object"]["sha"]
    commit=_api("GET", f"/git/commits/{head}")
    base_tree=commit["tree"]["sha"]
    remote=_remote_paths(base_tree)

    # Yerel değişikliğin başladığı içerik ile GitHub'daki içerik aynı değilse başka cihaz
    # ilerlemiştir. Force-push yerine dur; önce güncelleme/uzlaştırma yapılmalıdır.
    conflicts=[]
    for rel in paths:
        old=before.get(rel)
        remote_sha=remote.get(rel)
        from modules.source_sync import blob_matches
        if (remote_sha is not None if old is None else not blob_matches(rel, old, remote_sha)):
            conflicts.append(rel)
    if conflicts:
        raise RuntimeError("GitHub'da daha yeni/farklı sürüm var; üzerine yazılmadı: " + ", ".join(conflicts[:8]))

    entries=[]
    for rel in paths:
        f=ROOT/rel
        if not f.exists():
            if rel in remote:
                entries.append({"path":rel,"mode":"100644","type":"blob","sha":None})
            continue
        blob=_api("POST", "/git/blobs", {"content":base64.b64encode(f.read_bytes()).decode("ascii"),"encoding":"base64"})
        entries.append({"path":rel,"mode":"100644","type":"blob","sha":blob["sha"]})
    if not entries:
        forget_local(paths)
        return "GitHub zaten güncel."
    new_tree=_api("POST", "/git/trees", {"base_tree":base_tree,"tree":entries})["sha"]
    message="JARVIS: " + (summary.strip() or "otomatik geliştirme")[:180]
    new_commit=_api("POST", "/git/commits", {"message":message,"tree":new_tree,"parents":[head]})["sha"]
    # force=False: iki PC aynı anda ilerlerse GitHub fast-forward dışı yazmayı reddeder.
    _api("PATCH", f"/git/refs/heads/{updater.BRANCH}", {"sha":new_commit,"force":False})
    forget_local(paths)
    try:
        updater.mark_current(new_commit, message)
    except Exception:
        _record_failure('modules/git_publish.py:publish')
        pass
    return f"GitHub {updater.BRANCH} dalına gönderildi ({new_commit[:7]})."


_PUBLISH_EXT = {".py", ".js", ".html", ".css", ".md", ".txt", ".json", ".bat", ".toml", ".yaml", ".yml", ".java", ".gradle", ".properties", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff2", ".ico", ".jar"}
_PUBLISH_SKIP_PARTS = {".venv_install", ".venv_backup", ".jarvis", ".claude", "models", ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups", ".backups", ".gradle", "build", ".idea"}
_PUBLISH_SKIP_NAMES = {".env", "settings.json", "gemini_key.txt", "groq_key.txt", "github_token.txt", "phone_token.txt", "local.properties", "chat_sessions.json", "requests.json"}


def _publishable_files() -> dict[str, bytes]:
    """GitHub'a gönderilebilecek proje kaynaklarını döndür; kullanıcı verisi/gizli anahtarlar kapsam dışıdır."""
    out: dict[str, bytes] = {}
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _PUBLISH_SKIP_PARTS]
        bp = Path(base)
        for name in files:
            p = bp / name
            rel = p.relative_to(ROOT)
            if (name in _PUBLISH_SKIP_NAMES or name.startswith(".env.")
                    or (p.suffix.lower() not in _PUBLISH_EXT and name not in {".gitignore", ".gitattributes"}
                        and rel.as_posix() != "modules/desktop_uia.ps1")):
                continue
            if any(part in _PUBLISH_SKIP_PARTS for part in rel.parts):
                continue
            import updater
            if not updater._publishable_path(rel.as_posix()):   # kabul raporu gibi yerel çıktılar yayınlanmaz
                continue
            try:
                if p.stat().st_size > 20_000_000:
                    continue
                out[str(rel).replace("\\", "/")] = p.read_bytes()
            except OSError:
                continue
    return out


def _release_tests() -> None:
    """Development, local validation and publishing share one mandatory test suite."""
    from modules.validation import run_checks
    ok, log = run_checks(ROOT)
    if not ok:
        raise RuntimeError('Yayın doğrulaması başarısız: ' + log[-16000:])


def publish_worktree(summary: str = "kullanıcı onaylı yerel değişiklikler") -> str:
    """Bu PC'deki yerel kaynak farklarını açık kullanıcı komutuyla GitHub main'e yollar.

    Ev/İş ayrımı yoktur. Uzak main bu kurulumun kayıtlı taban commit'inden ilerlemişse yayın durur.
    Yayın öncesi çalışan .venv paketleri requirements.lock.txt dosyasına sabitlenir; silinen kaynak dosyaları da
    GitHub commit'ine silme olarak eklenir. Force-push kullanılmaz.
    """
    import updater

    ref = _api("GET", f"/git/ref/heads/{updater.BRANCH}")
    head = ref["object"]["sha"]
    base = str(updater.status().get("sha") or "")
    if not base:
        raise RuntimeError("Bu kurulumun GitHub taban sürümü bilinmiyor. Önce GitHub durumunu doğrula; kaynaklar birebir aynıysa taban otomatik düzeltilir.")
    if not head.startswith(base) and head != base:
        raise RuntimeError("GitHub main bu bilgisayarın taban sürümünden ileride. Önce GitHub durumunu doğrula/güncellemeyi uzlaştır; yerel dosyaların üzerine yazılmayacak.")

    # Çalışan Windows .venv içindeki gerçek sürümleri her kullanıcı onaylı yayında güncelle.
    # Test/CI gibi venv dışı ortamlarda tahmini lock üretme; mevcut lock varsa olduğu gibi yayınlanır.
    try:
        from modules import dependencies
        if dependencies.in_venv():
            dependencies.create_lock()
    except Exception as exc:  # noqa: BLE001
        _record_failure('modules/git_publish.py:publish_worktree')
        from modules.diagnostics import user_message
        raise RuntimeError("Paket sürümleri sabitlenemedi; GitHub yayını durduruldu: " + user_message(exc)) from None

    commit = _api("GET", f"/git/commits/{head}")
    base_tree = commit["tree"]["sha"]
    remote = _remote_paths(base_tree)
    local = _publishable_files()
    from modules.source_sync import blob_matches
    changed = {rel for rel, data in local.items() if not blob_matches(rel, data, remote.get(rel))}
    # Dosya gerçekten diskten silindiyse GitHub'dan da kaldır. Boyut nedeniyle publish listesine alınmayan mevcut dosyayı silme.
    deleted = {rel for rel in remote if updater._publishable_path(rel) and not (ROOT / rel).exists()}
    changed = sorted(changed | deleted)
    if not changed:
        forget_local(list(local_list()))
        updater.mark_current(head, commit.get("message", "") if isinstance(commit, dict) else "")
        return "GitHub zaten güncel; gönderilecek yerel kaynak değişikliği yok."
    if len(changed) > 500:
        raise RuntimeError(f"Tek yayında {len(changed)} dosya değişik görünüyor; güvenlik için yayın durduruldu.")

    _release_tests()
    entries = []
    for rel in changed:
        if rel in deleted:
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": None})
            continue
        blob = _api("POST", "/git/blobs", {"content": base64.b64encode(local[rel]).decode("ascii"), "encoding": "base64"})
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = _api("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})["sha"]
    message = "JARVIS: " + (summary.strip() or "kullanıcı onaylı yerel değişiklikler")[:180]
    new_commit = _api("POST", "/git/commits", {"message": message, "tree": new_tree, "parents": [head]})["sha"]
    _api("PATCH", f"/git/refs/heads/{updater.BRANCH}", {"sha": new_commit, "force": False})
    forget_local(changed)
    updater.mark_current(new_commit, message)
    return f"GitHub {updater.BRANCH} dalına {len(changed)} dosya gönderildi ({new_commit[:7]})."

