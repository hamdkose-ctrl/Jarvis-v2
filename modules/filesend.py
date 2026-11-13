"""Telefona dosya gönderme: Tailscale'in Taildrop özelliğiyle (aynı hesaptaki iPhone'a ya da Android telefona).

"Test planını telefonuma gönder", "son indirdiğim dosyayı telefona at", "ekran görüntüsünü telefona gönder".
iPhone'da dosya: Dosyalar → Tailscale klasörü. Android'de: İndirilenler klasörü.  Elle: dosyaya sağ tık → "Send with Tailscale".
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from config import load_settings, save_settings

_last_os: dict = {"os": "ios"}                  # son bulunan telefonun işletim sistemi (mesaj için)
# BRAIN-03: no global "last four files" across profiles. Only opaque
# owner-scoped, short-lived file observations; selection belongs to State Gate.
_pending_lock = threading.RLock()
_pending_by_owner: dict[str, dict] = {}
_PENDING_TTL = 180.0
_EXT_HINT = {"pdf": {".pdf"}, "fotograf": {".jpg", ".jpeg", ".png", ".heic"}, "resim": {".jpg", ".jpeg", ".png"},
             "cizim": {".dwg", ".pdf", ".dxf"}, "excel": {".xlsx", ".xls"}, "word": {".docx", ".doc"}}
_SKIP_EXT = {".tmp", ".crdownload", ".part", ".ini", ".lnk", ".url"}
ASK = ("Hangi dosyayı göndereyim? Adını ya da ne olduğunu söyle (örneğin “LGS programı PDF'i”, "
       "“son indirdiğim dosya” ya da “ekran görüntüsü”).")
# Dosyayı tarif etmeyen sözler: bunlarla rastgele dosya seçilmez, kullanıcıya sorulur
_VAGUE = re.compile(r"(?:bir\s+|bu\s+|şu\s+|o\s+)?(?:dosya\w*|belge\w*|şey\w*|bunu|şunu|onu|bu|şu|o|bir şey|birşey)?")


def _phone_name(p: dict, ip: str) -> str:
    """Telefonun görünen adı. iPhone'lar Tailscale'e adını "localhost" diye bildiriyor; o zaman DNS adı ya da tür."""
    host = str(p.get("HostName") or "").strip()
    if host and host.lower() not in ("localhost", "localhost.localdomain"):
        return host
    dns = str(p.get("DNSName") or "").split(".")[0].strip()
    if dns and not dns.lower().startswith("localhost"):
        return dns
    os_ = str(p.get("OS", "")).lower()
    return {"ios": "iPhone", "android": "Android"}.get(os_, ip)


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0


def _exe() -> str | None:
    from modules import phone
    return phone.tailscale_exe()


def phone_target() -> tuple[str, str] | None:
    """Gönderilecek telefon: (adres, görünen ad). Ayarlarda yoksa Tailscale'deki telefon otomatik bulunur
    (çevrimiçi olan önce; ikisi de çevrimiçiyse iPhone)."""
    exe = _exe()
    if not exe:
        return None
    saved = load_settings().get("send_target")
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8, creationflags=_flags())
        peers = (json.loads(r.stdout or "{}").get("Peer") or {}).values()
    except (OSError, subprocess.SubprocessError, ValueError):
        peers = []
    best = None
    for p in peers:
        ip = next((a for a in (p.get("TailscaleIPs") or []) if "." in a), "")
        name = _phone_name(p, ip)
        if not ip:
            continue
        os_ = str(p.get("OS", "")).lower()
        if saved and saved in (ip, name, str(p.get("HostName") or "")):
            _last_os["os"] = os_
            return ip, name
        if os_ in ("ios", "android"):
            rank = (1 if p.get("Online") else 0, 1 if os_ == "ios" else 0)
            if best is None or rank > best[0]:
                best = (rank, ip, name, os_)
    if best is None:
        return None
    _last_os["os"] = best[3]
    return best[1], best[2]


def send(path: Path) -> str:
    exe = _exe()
    if not exe:
        return "Tailscale bu bilgisayarda kurulu değil; telefona göndermek için Tailscale gerekli."
    tgt = phone_target()
    if not tgt:
        return "Tailscale'de telefonunu bulamadım. Telefonda Tailscale'in açık ve aynı hesapla giriş yapılmış olduğundan emin ol."
    if not path.is_file():
        return f"{path.name} dosyasını bulamadım."
    ip, name = tgt
    from modules import requests_state
    requests_state.check()
    mb = path.stat().st_size / 1_048_576
    try:
        r = subprocess.run([exe, "file", "cp", str(path), f"{ip}:"], capture_output=True, text=True,
                           timeout=600, creationflags=_flags())
    except subprocess.TimeoutExpired:
        return "Gönderim çok uzun sürdü; telefonun internete bağlı mı?"
    except OSError as e:
        return f"Gönderemedim: {e}"
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip().lower()
        if "offline" in err or "no route" in err or "timeout" in err:
            return f"{name} şu an çevrimdışı görünüyor. Telefonda Tailscale'i açıp tekrar dene."
        if "taildrop" in err or "not enabled" in err or "disabled" in err:
            return "Tailscale'de dosya gönderme (Taildrop) kapalı görünüyor; login.tailscale.com'da açman gerekebilir."
        return "Gönderemedim: " + (r.stderr or r.stdout or "bilinmeyen hata").strip()[:160]
    size = f"{mb:.1f} MB" if mb >= 1 else f"{max(1, round(mb * 1024))} KB"
    where = ("Telefonda İndirilenler klasörüne bak (Tailscale bildirimine dokunarak da açabilirsin)."
             if _last_os["os"] == "android" else "iPhone'da Dosyalar uygulamasında Tailscale klasörüne bak.")
    return f"{path.name} ({size}) {name} telefonuna gönderildi. {where}"


# ------------------------------------------------------------------ dosya bulma
def _folders() -> list[Path]:
    home = Path.home()
    out = []
    for c in ("Downloads", "İndirilenler", "Desktop", "Masaüstü", "OneDrive/Desktop", "OneDrive/Masaüstü", "Documents",
              "Belgeler", "Pictures/Screenshots", "Pictures"):
        p = home / c
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def _candidates(max_files: int = 4000) -> list[Path]:
    files, n = [], 0
    for root in _folders():
        for dirpath, dirs, names in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            dirs[:] = [d for d in dirs if not d.startswith(".") and depth < 2]
            for nm in names:
                p = Path(dirpath) / nm
                if p.suffix.lower() in _SKIP_EXT or nm.startswith("~$"):
                    continue
                files.append(p)
                n += 1
                if n >= max_files:
                    return files
    return files


_FOLD = str.maketrans("çğıöşüâîûÇĞIİÖŞÜ", "cgiosuaiucgiiosu")


def _norm(s: str) -> str:
    """Karşılaştırma için sadeleştir: Türkçe harfleri düzleştir (dosya adları çoğu zaman ASCII), _ ve - boşluk olsun."""
    s = s.translate(_FOLD).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def find(query: str) -> list[Path]:
    """Ada en çok benzeyen dosyalar (en iyi önce, eşitlikte en yeni)."""
    q = _norm(query)
    q = re.sub(r"\b(?:dosya\w*|belge\w*|su|bu|son|en|yeni)\b", " ", q).split()
    exts = set()
    for k, v in _EXT_HINT.items():
        if any(w.startswith(k) for w in q):
            exts |= v
            q = [w for w in q if not w.startswith(k)]
    if not q and not exts:
        return []
    scored = []
    for p in _candidates():
        if exts and p.suffix.lower() not in exts:
            continue
        name = _norm(p.stem)
        words = name.split()
        if q:
            hit = 0.0
            for w in q:
                stem = w[:max(4, len(w) - 3)]            # Türkçe ekleri tolere et: "planını" -> "plan"
                if stem in name:
                    hit += 1
                else:
                    best = max((difflib.SequenceMatcher(None, stem, x).ratio() for x in words), default=0)
                    hit += best if best >= .75 else 0
            score = hit / len(q)
            if score < .6:
                continue
        else:
            score = .7
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        scored.append((score, mt, p))
    scored.sort(key=lambda x: (round(x[0], 2), x[1]), reverse=True)
    return [p for _s, _m, p in scored[:5]]


def _score_gap(query: str, found: list[Path]) -> bool:
    """En iyi eşleşme ikinciden belirgin şekilde iyiyse sormadan gönder."""
    q = _norm(query).split()
    def sc(p: Path) -> float:
        name = _norm(p.stem)
        return sum(1 for w in q if w[:max(4, len(w) - 3)] in name) / max(1, len(q))
    return sc(found[0]) - sc(found[1]) >= .3


def _latest_download() -> Path | None:
    for c in ("Downloads", "İndirilenler"):
        d = Path.home() / c
        if d.is_dir():
            fs = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() not in _SKIP_EXT]
            if fs:
                return max(fs, key=lambda p: p.stat().st_mtime)
    return None


def _screenshot() -> Path:
    """Create a unique private screenshot, not a predictable global filename."""
    import pyautogui
    from modules import requests_state
    requests_state.check()
    with tempfile.NamedTemporaryFile(prefix="jarvis-taildrop-", suffix=".png", delete=False) as fd:
        p = Path(fd.name)
    try:
        pyautogui.screenshot(str(p))
        return p
    except BaseException:
        p.unlink(missing_ok=True)
        raise


def _ago(p: Path) -> str:
    d = time.time() - p.stat().st_mtime
    return "bugün" if d < 86400 else f"{int(d // 86400)} gün önce"


# ------------------------------------------------------------------ komutlar
# A trailing \w* turned "gönderme" (do NOT send) into "gönder".
# Only affirmative exact transfer verbs remain in the legacy fallback.
_TO_PHONE = re.compile(
    r"(.*?)\s*(?:'?[yn]?[ıiuü]\s+)?telefon(?:um)?[ay]?\s*"
    r"(?:gönder|at|yolla|aktar|ilet|gönderir misin|gönderebilir misin|atar mısın)"
    r"(?:\s+(?:lütfen|lutfen))?", re.I)


def _file_proof(path: Path) -> tuple | None:
    """Capture a confined, non-symlink candidate; never expose paths to Brain."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        resolved = path.resolve(strict=True)
        roots = [root.resolve(strict=True) for root in _folders()]
        if not any(resolved.is_relative_to(root) for root in roots):
            return None
        stat = path.stat()
        return (str(resolved), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError):
        return None


def remember_pending(owner: str, candidates: list[Path]) -> bool:
    """Open a bounded owner-local selection, never a global active user slot."""
    if not isinstance(owner, str) or not owner.strip():
        return False
    rows = []
    for path in candidates[:4]:
        proof = _file_proof(path)
        if proof is not None:
            rows.append((path, proof))
    with _pending_lock:
        _pending_by_owner.pop(owner, None)
        if len(rows) < 2:
            return False
        _pending_by_owner[owner] = {"expires": time.time() + _PENDING_TTL, "rows": rows}
    return True


def pending_choices(owner: str) -> tuple[tuple[str, ...], float] | None:
    """Read-only observation used by Brain's State Gate; no path/phone address."""
    with _pending_lock:
        state = _pending_by_owner.get(owner)
        if not state:
            return None
        if time.time() >= state["expires"]:
            _pending_by_owner.pop(owner, None)
            return None
        return (tuple(path.name for path, _ in state["rows"]), state["expires"])


def cancel_pending(owner: str) -> str:
    with _pending_lock:
        _pending_by_owner.pop(owner, None)
    return "Tamam, dosyayı göndermiyorum."


def select_pending(owner: str, index: int) -> str:
    """State-confirmed index only. Pop first: one request cannot replay/send twice."""
    from modules import requests_state
    requests_state.check()
    if not isinstance(owner, str) or not owner or type(index) is not int:
        return "Dosya seçimini doğrulayamadım; göndermedim."
    with _pending_lock:
        state = _pending_by_owner.pop(owner, None)
    if not state or time.time() >= state["expires"]:
        return "Dosya seçiminin süresi doldu; hiçbir dosya göndermedim."
    rows = state["rows"]
    if not 1 <= index <= len(rows):
        return "Geçersiz dosya numarası; hiçbir dosya göndermedim."
    path, expected = rows[index - 1]
    if _file_proof(path) != expected:
        return "Dosya değişmiş veya izinli klasör dışında; göndermedim."
    requests_state.check()
    return send(path)


def transfer_typed(owner: str, operation: str, query: str = "") -> str:
    """Core-selected transfer. No raw intent or arbitrary model path/phone."""
    from modules import requests_state
    requests_state.check()
    if not isinstance(owner, str) or not owner.strip():
        return "Dosya gönderim sahibini doğrulayamadım; göndermedim."
    cancel_pending(owner)
    if operation == "screenshot":
        from modules import privacy
        if (blocked := privacy.blocked("screen")):
            return blocked
        requests_state.check()
        path = _screenshot()
        try:
            return send(path).replace(path.name, "Ekran görüntüsü")
        finally:
            try:
                path.unlink()
            except OSError:
                pass
    if operation == "latest":
        path = _latest_download()
        if path is None:
            return "İndirilenler klasöründe dosya bulamadım."
        if _file_proof(path) is None:
            return "İndirilen dosyanın izinli ve değişmemiş bir dosya olduğunu doğrulayamadım; göndermedim."
        requests_state.check()
        return send(path)
    if operation != "search" or not isinstance(query, str) or not query.strip() or len(query) > 200:
        return "Dosyanın adını söyle; bu istek doğrulanamadı."
    found = find(query)
    if not found:
        return f"“{query}” adına benzeyen bir dosya bulamadım. İndirilenler, Masaüstü ve Belgeler'e baktım."
    if len(found) == 1 or _score_gap(query, found):
        if _file_proof(found[0]) is None:
            return "Dosya izinli klasörün dışında veya sembolik bağlantı; göndermedim."
        requests_state.check()
        return send(found[0])
    if not remember_pending(owner, found):
        return "Birkaç dosya eşleşiyor ama güvenli seçim açamadım. Dosyanın tam adını söyle."
    choices = pending_choices(owner)
    if choices is None:
        return "Dosya seçim kaydını doğrulayamadım; göndermedim."
    listed = "; ".join(f"{i}) {name}" for i, name in enumerate(choices[0], 1))
    return f"{len(choices[0])} dosya buldum, hangisini göndereyim? {listed}. Numarasını söylemen yeterli."


def handle(cmd_lower: str, *, owner: str | None = None) -> str | None:
    """Model-unavailable initial utterance adapter, not an effect owner."""
    t = cmd_lower.strip(" .!?")
    m = _TO_PHONE.fullmatch(t)
    if not m or not re.search(r"telefon", t):
        return None
    if not owner:
        return "Dosya gönderimi için kullanıcı doğrulanamadı; göndermedim."
    what = m.group(1).strip()
    if not what or _VAGUE.fullmatch(what):
        return ASK
    if re.search(r"ekran\s*görüntü|ekranı", what):
        return transfer_typed(owner, "screenshot")
    if re.search(r"son indir|indirdiğim|son dosya", what):
        return transfer_typed(owner, "latest")
    return transfer_typed(owner, "search", what)

def set_target(name: str) -> None:
    save_settings(send_target=name)
