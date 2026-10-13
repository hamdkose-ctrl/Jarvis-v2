"""JARVIS'in ana GitHub dalıyla güvenli sürüm eşitlemesi.

GitHub ortak ana geliştirme hedefidir. Açılışta yalnızca yeni sürüm kontrol edilir; hiçbir dosya otomatik çekilip kurulmaz.
Güncelleme ancak kullanıcının açık isteğiyle kurulur. Yerel değişiklikler yalnız açık yükleme isteğiyle yayınlanır.
Program dışı .venv ve ~/.jarvis kullanıcı verisine dokunulmaz.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import base64
import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "hamdkose-ctrl/Jarvis"
BRANCH = "main"
ROOT = Path(__file__).resolve().parent              # Jarvis klasörü
DATA = Path(os.environ.get("JARVIS_DATA_DIR") or (Path.home() / ".jarvis"))
STATE = DATA / "update.json"
TOKEN_FILE = DATA / "github_token.txt"
SKIP = {".venv", "__pycache__", ".git", ".github", ".gradle", "build", ".idea"}   # generated build trees are excluded
TIMEOUT = 4


def _settings() -> dict:
    try:
        return json.loads((DATA / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(**ch) -> None:
    s = _state()
    s.update(ch)
    try:
        DATA.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _unprotect(stored: str) -> str:
    """privacy.protect ile kaydedilmiş anahtarı çözer (Windows DPAPI / base64 / düz)."""
    stored = stored.strip()
    try:
        if stored.startswith("dpapi:") and sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

            raw = base64.b64decode(stored[6:])
            buf = ctypes.create_string_buffer(raw, len(raw))
            inp, out = BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
            if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0,
                                                           ctypes.byref(out)):
                return ""
            try:
                return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
            finally:
                ctypes.windll.kernel32.LocalFree(out.pbData)
        if stored.startswith("b64:"):
            return base64.b64decode(stored[4:]).decode("utf-8")
    except Exception:       # noqa: BLE001
        _record_failure('updater.py:_unprotect')
        return ""
    return stored


def _token() -> str:
    tok = os.environ.get("JARVIS_GH_TOKEN", "")
    if not tok and TOKEN_FILE.exists():
        try:
            tok = _unprotect(TOKEN_FILE.read_text(encoding="utf-8"))
        except OSError:
            tok = ""
    return tok.strip()


def save_token(token: str) -> None:
    """Gizli depoyu okuyabilmek için GitHub erişim anahtarını korumalı kaydeder (Ayarlar'dan çağrılır)."""
    try:
        from modules import privacy
        text = privacy.protect(token.strip())
    except Exception:       # noqa: BLE001
        _record_failure('updater.py:save_token')
        text = "b64:" + base64.b64encode(token.strip().encode()).decode()
    DATA.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(text, encoding="utf-8")


def _get(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "jarvis-updater"})
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest() -> dict | None:
    """Depodaki en son sürüm: {"sha", "msg", "date"}; ulaşılamazsa None."""
    try:
        d = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))
        return {"sha": d["sha"], "msg": (d.get("commit", {}).get("message") or "").split("\n")[0][:120],
                "date": d.get("commit", {}).get("committer", {}).get("date", "")}
    except urllib.error.HTTPError as e:
        why = "erişim izni yok (gizli depo için anahtar gerekli)" if e.code in (401, 403, 404) else f"GitHub {e.code}"
        _save_state(last_error=f"{time.strftime('%Y-%m-%d %H:%M')} {why}")
        return None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None                       # internet yok: sessizce atla


def _validate(files: dict[str, bytes]) -> str | None:
    """İndirilen Python dosyaları sözdizimi açısından sağlam mı? Sorun varsa açıklaması döner."""
    if "main.py" not in files or "web.py" not in files:
        return "eksik indirme"
    for name, data in files.items():
        if name.endswith(".py"):
            try:
                compile(data, name, "exec")
            except SyntaxError as e:
                return f"{name}: {e}"
    return None




def _publishable_path(rel: str) -> bool:
    allowed = {".py", ".js", ".html", ".css", ".md", ".txt", ".json", ".bat", ".toml", ".yaml", ".yml", ".java", ".gradle", ".properties", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff2", ".ico", ".jar"}
    skip_parts = {".venv_install", ".venv_backup", ".jarvis", ".claude", "models", ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups", ".backups", ".gradle", "build", ".idea"}
    skip_names = {".env", "settings.json", "gemini_key.txt", "groq_key.txt", "github_token.txt", "phone_token.txt", "local.properties", "chat_sessions.json", "requests.json"}
    pp = Path(rel)
    return (pp.name not in skip_names and not pp.name.startswith(".env.")
            and (pp.suffix.lower() in allowed or pp.name in {".gitignore", ".gitattributes"} or pp.as_posix() == "modules/desktop_uia.ps1")
            and not any(x in skip_parts for x in pp.parts))


def _source_changes_against(sha: str, limit: int = 120) -> list[str]:
    """Yerel yayınlanabilir kaynak ağacını belirli GitHub commit'iyle karşılaştırır; silinen dosyaları da görür."""
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{sha}?recursive=1", timeout=12))
    if tree.get("truncated"):
        raise RuntimeError("GitHub ağaç listesi eksik; yerel değişiklik güvenlik kontrolü yapılamadı")
    remote = {x.get("path"): x.get("sha") for x in tree.get("tree", [])
              if x.get("type") == "blob" and _publishable_path(str(x.get("path") or ""))}
    from modules.source_sync import blob_matches
    local: dict[str, bool] = {}
    for base_dir, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {".venv_install", ".venv_backup", ".jarvis", ".claude", "models", ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups", ".backups", ".gradle", "build", ".idea"}]
        bp = Path(base_dir)
        for name in names:
            f = bp / name
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            if not _publishable_path(rel):
                continue
            try:
                data = f.read_bytes()
            except OSError:
                continue
            local[rel] = blob_matches(rel, data, remote.get(rel))
    changed = sorted(set(rel for rel, matches in local.items() if not matches) |
                     set(rel for rel in remote if rel not in local))
    return changed[:limit]


def _local_source_changes() -> list[str]:
    """Kayıtlı GitHub tabanına göre bu PC'de değiştirilmiş kaynakları bulur."""
    base = str(_state().get("sha") or "")
    if not base:
        raise RuntimeError("Yerel taban commit bilinmiyor; güncelleme güvenlik için durduruldu.")
    try:
        return _source_changes_against(base, 20)
    except Exception as exc:  # noqa: BLE001
        _record_failure('updater.py:_local_source_changes')
        raise RuntimeError(f"Yerel değişiklik güvenlik kontrolü yapılamadı: {exc}") from exc


def _compare_commits(base: str, remote: str) -> str:
    """GitHub compare API ile remote commit'in kayıtlı tabana göre konumunu döndürür.

    Sonuç: identical | ahead | behind | diverged | unknown. SHA metinlerini prefix diye
    karşılaştırmak commit soyunu göstermez; bu yüzden gerçek commit grafiğine bakılır.
    """
    if not base or not remote:
        return "unknown"
    if base == remote:
        return "identical"
    try:
        d = json.loads(_get(f"https://api.github.com/repos/{REPO}/compare/{base}...{remote}", timeout=12))
        status_ = str(d.get("status") or "").lower()
        return status_ if status_ in {"identical", "ahead", "behind", "diverged"} else "unknown"
    except Exception:  # noqa: BLE001 - doğrulama güvenli biçimde unknown'a düşer
        _record_failure('updater.py:_compare_commits')
        return "unknown"


def verify_sync() -> dict:
    """GitHub main ile gerçek kaynak ağacını ve commit soyunu karşılaştırır.

    state: synced | local_changes | remote_ahead | diverged | unknown | offline
    """
    st = status()
    info = latest()
    if not info:
        _save_state(sync_state="offline", sync_msg="GitHub doğrulanamadı; bağlantı/anahtar kontrol edilmeli.", verified_at=time.strftime("%Y-%m-%d %H:%M"))
        return {**st, "verified": False, "sync_state": "offline", "sync_msg": "GitHub doğrulanamadı; bağlantı/anahtar kontrol edilmeli."}
    remote_sha = str(info.get("sha") or "")
    base = str(_state().get("sha") or "")
    try:
        changes_remote = _source_changes_against(remote_sha, 120)
    except Exception as exc:  # noqa: BLE001
        _record_failure('updater.py:verify_sync')
        return {**st, "verified": False, "remote_sha": remote_sha[:7], "sync_state": "unknown", "sync_msg": f"Kaynak karşılaştırılamadı: {exc}"}

    if not changes_remote:
        state, msg = "synced", "Bu bilgisayarın kaynakları GitHub main ile birebir aynı."
        if base != remote_sha:
            mark_current(remote_sha, str(info.get("msg") or ""))
    elif not base:
        state, msg = "unknown", "Yerel taban commit bilinmiyor ve kaynaklar GitHub main ile farklı; otomatik işlem güvenlik için durduruldu."
    else:
        try:
            changes_base = _source_changes_against(base, 120)
        except Exception as exc:  # noqa: BLE001
            _record_failure('updater.py:verify_sync')
            state, msg = "unknown", f"Yerel taban karşılaştırılamadı: {exc}"
        else:
            relation = _compare_commits(base, remote_sha)
            local_dirty = bool(changes_base)
            if relation == "identical":
                state, msg = "local_changes", f"GitHub'a gönderilmemiş {len(changes_remote)} yerel kaynak değişikliği var."
            elif relation == "ahead" and not local_dirty:
                state, msg = "remote_ahead", "GitHub main bu bilgisayardan ileride. Yerel kaynak değişikliği yok; güvenle GitHub'dan alınabilir."
            elif relation == "ahead" and local_dirty:
                state, msg = "diverged", "GitHub main ilerlemiş ve bu bilgisayarda da yerel kaynak değişiklikleri var. Otomatik üzerine yazılmayacak."
            elif relation == "diverged":
                state, msg = "diverged", "GitHub main ile bu bilgisayarın kayıtlı tabanı ayrışmış. Otomatik üzerine yazılmayacak."
            elif relation == "behind":
                state, msg = "local_changes", "GitHub main bu bilgisayarın kayıtlı sürümünden geride. Yerel sürüm korunacak; önce güncel kaynakları GitHub'a eşitle."
            else:
                state, msg = "unknown", "GitHub commit ilişkisi güvenli biçimde doğrulanamadı; otomatik işlem durduruldu."
    local_count = len(changes_remote) if state in ("local_changes", "diverged") else 0
    _save_state(sync_state=state, sync_msg=msg, verified_remote_sha=remote_sha, verified_at=time.strftime("%Y-%m-%d %H:%M"),
                local_change_count=local_count)
    return {**status(), "verified": True, "remote_sha": remote_sha[:7], "sync_state": state,
            "sync_msg": msg, "local_changes": changes_remote[:20], "local_change_count": local_count}

def apply(info: dict, backed_up: bool = False) -> str:
    """Belirtilen sürümü indirip kurar. Dönüş: kullanıcıya söylenecek kısa cümle.

    backed_up=True yalnız backup_and_pull'dan gelir: farklı yerel dosyalar önce yedeklendiği için
    yerel değişiklik/ayrışma engeli atlanır; daha eski commit kurulmaz. Aday testleri ve geri alma aynen çalışır.
    """
    import release_guard
    if release_guard.pending(ROOT):
        raise RuntimeError("Geliştirme işlemi açılış onayı veya geri alma bekliyor; GitHub güncellemesi kurulmadı. Önce geliştirmeyi tamamla veya geri al.")
    if backed_up and _compare_commits(str(_state().get("sha") or ""), str(info.get("sha") or "")) == "behind":
        raise RuntimeError("GitHub sürümü bu bilgisayarın kayıtlı sürümünden eski; yedek alınmış olsa da kurulmadı. Güncel yerel sürümü önce GitHub'a eşitle.")
    if not backed_up:
        local = _protected_local_changes()
        if local:
            raise RuntimeError("Bu bilgisayarda GitHub'a gönderilmemiş yerel kaynak değişiklikleri var; güncelleme kurulmadı. Önce ‘git yükle’ de veya geri al.")
        manual = _local_source_changes()
        if manual:
            sample = ", ".join(manual[:6])
            raise RuntimeError(f"Bu bilgisayarda GitHub'a gönderilmemiş yerel kaynak değişiklikleri var ({sample}); güncelleme kurulmadı. Önce ‘git yükle’ de.")
        base = str(_state().get("sha") or "")
        if _compare_commits(base, str(info.get("sha") or "")) not in ("ahead", "identical"):
            raise RuntimeError("Güncellemenin commit ilişkisi güvenle doğrulanamadı; kurulmadı.")
    raw = _get(f"https://api.github.com/repos/{REPO}/zipball/{info['sha']}", timeout=60)
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for item in z.infolist():
            if item.is_dir():
                continue
            parts = item.filename.split("/")[1:]          # en üstteki "sahip-depo-sha/" klasörünü at
            if not parts or any(p in SKIP for p in parts) or parts[-1].endswith(".pyc"):
                continue
            rel = "/".join(parts)
            if _publishable_path(rel):
                files[rel] = z.read(item)
    bad = _validate(files)
    if bad:
        raise ValueError(f"İndirilen sürüm bozuk, kurulmadı ({bad})")

    # Prepare the complete mutation set before touching any source file.
    from modules import requests_state
    requests_state.check()
    for name in files:
        pp = Path(name)
        if pp.is_absolute() or ".." in pp.parts or ROOT.resolve() not in (ROOT / pp).resolve().parents:
            raise ValueError("İndirilen sürümde güvenli olmayan dosya yolu var.")
    mutations = {}
    for base_dir, dirs, names in os.walk(ROOT, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP | {"venv", "node_modules", ".pytest_cache", "backups", ".backups"} and not (Path(base_dir) / d).is_symlink()]
        for leaf in names:
            dest = Path(base_dir) / leaf
            rel = dest.relative_to(ROOT).as_posix()
            if _publishable_path(rel) and rel not in files:
                mutations[rel] = None
    for name, data in files.items():
        dest = release_guard.safe_path(ROOT, name)
        if not dest.exists() or dest.read_bytes() != data:
            mutations[name] = data
    if not mutations:
        return "Kaynak dosyaları zaten güncel."
    from modules import release_workspace
    originals = {name: release_guard.contents(release_guard.safe_path(ROOT, name)) for name in mutations}
    new_python = None
    transaction = None
    previous_state = _state()
    try:
        requests_state.allow_long_operation(600)
        # Official GitHub releases are authorized to update recovery infrastructure;
        # development drafts keep candidate()'s protected-file rejection.
        with release_workspace.candidate(ROOT, mutations, allow_protected=True) as candidate:
            new_python = release_workspace.changed_environment(candidate, mutations, ROOT)
            ok, log = release_workspace.validate(candidate, ROOT, new_python)
            if not ok:
                raise RuntimeError("Aday güncelleme testleri başarısız; kaynaklar değiştirilmedi. " + log[-4000:])
        requests_state.check()
        for name, original in originals.items():
            if release_guard.contents(release_guard.safe_path(ROOT, name)) != original:
                raise ValueError(name + " test sırasında değişmiş; güncelleme durduruldu.")
        records = {name: {'before': base64.b64encode(original).decode() if original is not None else None,
                          'after': release_guard.digest(mutations[name])} for name, original in originals.items()}
        transaction = release_guard.prepare(ROOT, records, 'github-update', new_python)
        transaction['development_state_path'] = str(STATE)
        transaction['development_state_before'] = previous_state
        transaction['update_sha'] = info['sha']
        release_guard.update(ROOT, transaction, 'applying')
        for name, data in mutations.items():
            requests_state.check()
            dest = release_guard.safe_path(ROOT, name)
            if data is None:
                dest.unlink(missing_ok=True)
            else:
                release_guard.atomic(dest, data)
        note = f"GitHub güncellemesi aday testlerinden geçti ve uygulandı ({len(mutations)} dosya): {info['msg']}. Güvenli açılış denetimi için Jarvis’i yeniden başlat."
        next_state = dict(previous_state, sha=info['sha'], msg=info['msg'], date=info['date'],
                          applied=time.strftime("%Y-%m-%d %H:%M"), notice=note)
        release_guard.save(STATE, next_state)
        release_guard.installed(ROOT, transaction)
    except BaseException:
        _record_failure('updater.py:safe_apply')
        if transaction is not None:
            release_guard.restore(ROOT, transaction)
        release_workspace.discard_environment(ROOT, new_python)
        raise
    return note



_SC_LOCAL = DATA / "selfcoder" / "local_changes.json"


def backup_and_pull() -> dict:
    """Çakışmada çıkış yolu: GitHub'dan farklı yerel dosyaları ~/.jarvis/yerel_yedek altına kopyalar, sonra main'i kurar.

    Yalnız açık kullanıcı onayıyla çağrılır. Yedek tamamlanmadan hiçbir kaynak dosyası değişmez.
    """
    info = latest()
    if not info:
        raise RuntimeError("GitHub'a ulaşılamadı; hiçbir dosya değiştirilmedi.")
    if _compare_commits(str(_state().get("sha") or ""), str(info.get("sha") or "")) == "behind":
        raise RuntimeError("GitHub sürümü bu bilgisayarın kayıtlı sürümünden eski; hiçbir dosya değiştirilmedi. Güncel yerel sürümü önce GitHub'a eşitle.")
    changed = _source_changes_against(info["sha"], 5000)
    folder = DATA / "yerel_yedek" / time.strftime("%Y%m%d-%H%M%S")
    saved, remote_only = [], []
    for rel in changed:
        src = ROOT / rel
        if not src.is_file():
            remote_only.append(rel)
            continue
        dest = folder / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        saved.append(rel)
    if _SC_LOCAL.exists():
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SC_LOCAL, folder / "selfcoder_local_changes.json")
    if saved or remote_only:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "LISTE.txt").write_text(
            "Yedeklenen (bu bilgisayarda GitHub'dan farklı olan) dosyalar:\n" + "\n".join(saved or ["-"]) +
            "\n\nYalnız GitHub'da olan, bu bilgisayara eklenecek dosyalar:\n" + "\n".join(remote_only or ["-"]) + "\n",
            encoding="utf-8")
    note = apply(info, backed_up=True)
    _save_local_changes({})
    mark_current(info["sha"], str(info.get("msg") or ""))
    _save_state(notice=note)
    return {"note": note, "backup": str(folder) if saved else "", "saved": saved, "added": remote_only}


def _protected_local_changes() -> dict:
    """Önceki kurulumlardan kalan yerel kaynak değişikliklerinin güvenli güncelleme kaydı."""
    try:
        d = json.loads(_SC_LOCAL.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_local_changes(d: dict) -> None:
    try:
        if _SC_LOCAL.exists() or d:
            _SC_LOCAL.parent.mkdir(parents=True, exist_ok=True)
            _SC_LOCAL.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _cleanup_backups(keep: int = 3) -> None:
    d = DATA / "update_backup"
    if d.is_dir():
        olds = sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in olds[keep:]:
            shutil.rmtree(p, ignore_errors=True)


def check(apply_now: bool = False, force: bool = False) -> str | None:
    """Yeni sürümü kontrol eder. Varsayılan salt-okunurdur; dosya değiştirmez.

    apply_now=True yalnız açık kullanıcı onayı/komutu sonrasında kullanılmalıdır.
    Açılış akışı bu fonksiyonu apply_now=False ile çağırır.
    """
    if not force and _settings().get("update_check", True) is False:
        return None
    info = latest()
    if not info or info["sha"] == _state().get("sha"):
        return None
    if _compare_commits(str(_state().get("sha") or ""), str(info.get("sha") or "")) == "behind":
        _save_state(pending_sha="", pending_msg="", pending_date="")
        return "GitHub sürümü bu bilgisayarın kayıtlı sürümünden geride; yerel sürüm korundu."
    _save_state(pending_sha=info["sha"], pending_msg=info["msg"], pending_date=info["date"])
    if not apply_now:
        return f"Yeni sürüm var: {info['msg']} (kurulmadı)"
    try:
        note = apply(info) or None
        _save_state(pending_sha="", pending_msg="", pending_date="")
        return note
    except Exception as e:  # noqa: BLE001
        _record_failure('updater.py:check')
        _save_state(last_error=f"{time.strftime('%Y-%m-%d %H:%M')} {type(e).__name__}: {e}"[:300])
        return None


def install_latest(force: bool = True) -> str | None:
    """Kullanıcının açık güncelleme isteği sonrası en son sürümü kurar."""
    return check(apply_now=True, force=force)



def mark_current(sha: str, msg: str = "") -> None:
    """Bu çalışma ağacının az önce GitHub'a yayınlanan/doğrulanan commit ile aynı olduğunu kaydet."""
    _save_state(sha=sha, msg=msg, date=time.strftime("%Y-%m-%dT%H:%M:%S"),
                applied=time.strftime("%Y-%m-%d %H:%M"), last_error="", sync_state="synced", local_change_count=0,
                sync_msg="Bu bilgisayarın kaynakları GitHub main ile birebir aynı.",
                verified_remote_sha=sha, verified_at=time.strftime("%Y-%m-%d %H:%M"))

def pop_notice() -> str | None:
    """Son güncellemenin bildirimini bir kez verir (Jarvis açıldıktan sonra ekranda/sesli söylenir)."""
    s = _state()
    note = s.get("notice")
    if note:
        _save_state(notice=None)
    return note


def status() -> dict:
    s = _state()
    return {"sha": (s.get("sha") or "")[:7], "msg": s.get("msg", ""), "applied": s.get("applied", ""),
            "error": s.get("last_error", ""), "auto": False,
            "check_on_start": _settings().get("update_check", True) is not False,
            "pending_sha": (s.get("pending_sha") or "")[:7], "pending_msg": s.get("pending_msg", ""),
            "token": bool(_token()), "sync_state": s.get("sync_state", ""), "sync_msg": s.get("sync_msg", ""),
            "remote_sha": (s.get("verified_remote_sha") or "")[:7], "verified_at": s.get("verified_at", ""),
            "local_count": int(s.get("local_change_count") or 0)}


if __name__ == "__main__":                 # elle deneme: python updater.py
    print(check(apply_now=False, force=True) or "Güncel.")
    print(status())
