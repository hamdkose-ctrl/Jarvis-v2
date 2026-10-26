"""Klasör izleme: "İndirilenler'i izle, PDF gelince önemli yerleri tablo yap".

- 20 saniyede bir yalnız kural verilen klasörün dosya listesine (ad, boyut, tarih) bakılır; alt klasörlere inilmez,
  dosya içi okunmaz. Model yalnız kurala uyan yeni bir dosya için çağrılır.
- Yalnız PC'de o an aktif kullanıcının kuralları çalışır (başka kullanıcının anahtarı harcanmaz).
- Kural kurulmadan önce klasörde olan dosyalara dokunulmaz. İnmekte olan dosya boyutu sabitlenene kadar beklenir.
- Jarvis'in kendi ürettiği dosyalar tekrar işlenmez. Saatte en fazla HOURLY_LIMIT dosya kendiliğinden işlenir;
  fazlası bekletilir ve kullanıcıya sorulur.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from config import DATA_DIR
from modules import docs
from modules.diagnostics import record_failure as _record_failure

INTERVAL = 20             # saniye
HOURLY_LIMIT = 5          # kullanıcı başına saatte kendiliğinden işlenen dosya
MAX_ENTRIES = 5000        # bir klasörde bakılan en fazla dosya
MAX_RULES = 10
_PARTIAL = {".crdownload", ".tmp", ".part", ".partial", ".download", ".opdownload"}
_LOCK = threading.RLock()
_STATE: dict = {}         # kural kimliği -> {"sizes": {ad: boyut}}; boyut sabitlenme takibi (bellekte)
_RECENT: dict = {}        # kullanıcı -> son bir saatte işlenen dosya zamanları
_PENDING: dict = {}       # kullanıcı -> [(kural, yol)] kota yüzünden bekleyenler
OUTPUTS: set = set()      # Jarvis'in ürettiği dosyalar (döngü olmasın)

_FOLDERS = {"indirilenler": "Downloads", "indirilen": "Downloads", "downloads": "Downloads",
            "masaüstü": "Desktop", "masaustu": "Desktop", "desktop": "Desktop",
            "belgeler": "Documents", "belgelerim": "Documents", "documents": "Documents",
            "resimler": "Pictures", "resimlerim": "Pictures", "pictures": "Pictures"}
_TR_NAMES = {"Downloads": "İndirilenler", "Desktop": "Masaüstü", "Documents": "Belgeler", "Pictures": "Resimler"}
_KINDS = {"pdf": {".pdf"}, "word": {".docx"}, "excel": {".xlsx", ".xlsm", ".csv"}, "csv": {".csv"},
          "powerpoint": {".pptx"}, "sunum": {".pptx"}, "görsel": {".png", ".jpg", ".jpeg", ".webp"},
          "resim": {".png", ".jpg", ".jpeg", ".webp"}}


def _low(s: str) -> str:
    return str(s or "").replace("I", "ı").replace("İ", "i").lower()


# ------------------------------------------------------------------ kural kaydı

def _file(owner: str) -> Path:
    return DATA_DIR / "izleme" / f"{re.sub(r'[^a-z0-9_-]', '_', owner)}.json"


def load(owner: str) -> list[dict]:
    try:
        data = json.loads(_file(owner).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        _record_failure('modules/watcher.py:load')
        return []


def _save(owner: str, rules: list[dict]) -> None:
    path = _file(owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


def resolve_folder(word: str) -> Path | None:
    from modules import nxapi
    low = _low(word).strip(" '’")
    for cand in (low, re.sub(r"(?:'|’)?(?:n[ıiuü]|[ıiuü]|n)$", "", low)):   # "Masaüstünü", "Belgeleri"
        if cand in ("jarvis dosyaları", "jarvis dosyalari", "yüklediklerim"):
            return nxapi.FILES_DIR
        name = _FOLDERS.get(cand)
        if name:
            break
    else:
        return None
    return nxapi.home_folder(name) or nxapi.HOME / name


def folder_label(folder: str | Path) -> str:
    p = Path(folder)
    return "Jarvis Dosyaları" if p.name == "Jarvis Dosyaları" else _TR_NAMES.get(p.name, p.name)


def _birth(st) -> float:
    # Windows'ta st_ctime oluşturma zamanıdır; kopyalanan dosya eski değişiklik tarihini taşısa da yeni sayılır.
    return max(st.st_mtime, getattr(st, "st_birthtime", 0) or st.st_ctime)


def add_rule(owner: str, folder: Path, exts: list[str], action: str, instruction: str) -> dict:
    from modules import nxapi
    if nxapi.allowed(folder) is None or not folder.is_dir():
        raise ValueError("Bu klasörü izleyemem. İndirilenler, Masaüstü, Belgeler, Resimler veya Jarvis Dosyaları olabilir.")
    with _LOCK:
        rules = load(owner)
        if len(rules) >= MAX_RULES:
            raise ValueError(f"En fazla {MAX_RULES} izleme kuralı olabilir; önce birini durdur.")
        rule = {"id": uuid.uuid4().hex[:8], "folder": str(folder), "exts": sorted(exts), "action": action,
                "instruction": instruction[:300], "since": time.time(), "paused": False}
        rules.append(rule)
        _save(owner, rules)
    return rule


def describe(rule: dict) -> str:
    kinds = ", ".join(e.lstrip(".").upper() for e in rule["exts"]) or "her desteklenen dosya"
    what = {"notify": "haber veririm", "summary": "özetlerim"}.get(rule["action"], f"“{rule['instruction']}”")
    return f"{folder_label(rule['folder'])}: {kinds} gelince {what}" + (" (duraklatıldı)" if rule.get("paused") else "")


# ------------------------------------------------------------------ komutlar

_WATCH = re.compile(r"^(.+?)(?:'?[ıiuü]|’[ıiuü]|\s+klasörünü)?\s+izle\b[,.]?\s*(.*)$", re.I)
_WHEN = re.compile(r"\b(gelince|gelirse|düşünce|düşerse|inince|inerse|eklenince|eklenirse)\b[,]?\s*", re.I)


def handle(owner: str, command: str) -> str | None:
    text = (command or "").strip().rstrip(".!")
    low = _low(text)
    if re.fullmatch(r"(izlenen klasörler(im)?|klasör izlemeleri(ni)?( listele| göster)?|izleme kuralları(nı)?( göster| listele)?)", low):
        rules = load(owner)
        return ("İzlenen klasörler:\n" + "\n".join(f"• {describe(r)}" for r in rules)) if rules else "İzlenen klasör yok."
    m = re.fullmatch(r"(?:(.+?)\s+)?(?:klasör\s+)?izleme(?:yi|sini|lerini|leri)?\s+(durdur|kapat|sil|iptal et)", low)
    if m and load(owner) and (not m.group(1) or resolve_folder(m.group(1)) is not None):
        return stop(owner, m.group(1))   # "videoyu izlemeyi durdur" gibi başka işler buraya düşmez
    if re.fullmatch(r"bekleyen (dosyaları|dosyalari) işle", low):
        return run_pending(owner)
    m = _WATCH.match(text)
    if not m:
        return None
    folder = resolve_folder(m.group(1))
    if folder is None:
        return None
    rest = m.group(2).strip()
    parts = _WHEN.split(rest, maxsplit=1)
    head, action_text = (parts[0], parts[2]) if len(parts) == 3 else ("", rest)
    exts = sorted({e for word, kind in _KINDS.items() if word in _low(head) for e in kind})
    act = _low(action_text)
    from modules import workbench
    if not action_text or re.search(r"haber ver|bildir|söyle", act):
        action = "notify"
    elif re.search(r"özet", act) and not workbench.wants(action_text):
        action = "summary"
    elif workbench.wants(action_text):
        action = "workbench"
    else:
        return ("Ne yapacağımı anlayamadım. Örnek: “İndirilenler'i izle, PDF gelince önemli yerleri tablo yap”, "
                "“Masaüstünü izle, Excel gelince haber ver” veya “… PDF gelince özetle”.")
    try:
        rule = add_rule(owner, folder, exts, action, action_text)
    except ValueError as e:
        return str(e)
    return (f"Tamam, izliyorum. {describe(rule)}.\nKlasörde şu an olan dosyalara dokunmam; saatte en fazla "
            f"{HOURLY_LIMIT} dosyayı kendiliğinden işlerim. Kapatmak için “izlemeyi durdur” de.")


def stop(owner: str, which: str | None = None) -> str:
    with _LOCK:
        rules = load(owner)
        if not rules:
            return "İzlenen klasör yok."
        folder = resolve_folder(which) if which else None
        keep = [r for r in rules if folder is not None and Path(r["folder"]) != folder]
        gone = len(rules) - len(keep)
        if not gone:
            return "Bu klasör için izleme kuralı yok."
        _save(owner, keep)
        _PENDING.pop(owner, None)
    return f"{gone} izleme kuralı kapatıldı."


# ------------------------------------------------------------------ tarama

def scan(rule: dict, now: float) -> list[Path]:
    """Kuraldan sonra gelen ve boyutu sabitlenmiş dosyalar."""
    folder = Path(rule["folder"])
    state = _STATE.setdefault(rule["id"], {"sizes": {}})
    done = set(rule.get("done") or [])
    ready, sizes = [], {}
    with os.scandir(folder) as entries:
        for n, entry in enumerate(entries):
            if n >= MAX_ENTRIES:
                break
            name = entry.name
            ext = os.path.splitext(name)[1].lower()
            if name.startswith(("~$", ".")) or ext in _PARTIAL or not entry.is_file(follow_symlinks=False):
                continue
            if name in done or (rule["exts"] and ext not in rule["exts"]):
                continue
            if not rule["exts"] and ext not in docs.SUPPORTED:
                continue
            st = entry.stat(follow_symlinks=False)
            if _birth(st) <= rule["since"] or st.st_size == 0:
                continue
            path = str(Path(entry.path).resolve())
            if path in OUTPUTS:
                continue
            sizes[name] = st.st_size
            if state["sizes"].get(name) == st.st_size:      # iki taramada aynı boyut: inmesi bitti
                ready.append(Path(entry.path))
    state["sizes"] = {k: v for k, v in sizes.items() if k not in {p.name for p in ready}}
    return ready


def process(owner: str, rule: dict, path: Path) -> str:
    if rule["action"] == "notify":
        return f"{folder_label(rule['folder'])} klasörüne yeni dosya geldi: {path.name}"
    if rule["action"] == "summary":
        return f"{path.name} geldi, özeti:\n\n" + docs.summarize(str(path))
    from modules import workbench
    if path.suffix.lower() not in docs.SUPPORTED:
        return f"{path.name} geldi ama bu türde tablo işi yapamıyorum."
    answer = workbench.handle(owner, [str(path)], rule["instruction"])
    m = re.match(r"Hazır: (.+)", answer)
    if m:
        OUTPUTS.add(str(Path(m.group(1).strip()).resolve()))
    return f"{path.name} geldi. " + answer


def _allowed_now(owner: str, now: float) -> bool:
    recent = [t for t in _RECENT.get(owner, []) if now - t < 3600]
    _RECENT[owner] = recent
    return len(recent) < HOURLY_LIMIT


def tick(owner: str, emit, now: float | None = None) -> None:
    """Bir tarama turu. emit(text) sonucu kullanıcının sohbetine yazar."""
    now = now or time.time()
    with _LOCK:
        rules = load(owner)
    changed, work, held = False, [], []
    for rule in rules:
        if rule.get("paused"):
            continue
        try:
            found = scan(rule, now)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            rule["paused"] = True
            changed = True
            emit(f"{folder_label(rule['folder'])} klasörüne erişemiyorum; izlemeyi duraklattım.")
            continue
        for path in found:
            if _allowed_now(owner, now):
                _RECENT[owner].append(now)
                work.append((rule, path))
            else:
                _PENDING.setdefault(owner, []).append((rule, path))
                held.append((rule, path))
    handled = {}
    for rule, path in work + held:
        handled.setdefault(rule["id"], []).append(path.name)
    if changed or handled:
        with _LOCK:   # kalıcı: duraklatılan kurallar ve işlenen dosya adları (yeniden başlatınca tekrar işlenmesin)
            current = load(owner)
            paused = {r["id"] for r in rules if r.get("paused")}
            for r in current:
                if r["id"] in paused:
                    r["paused"] = True
                if handled.get(r["id"]):
                    r["done"] = (list(r.get("done") or []) + handled[r["id"]])[-500:]
            _save(owner, current)
    for rule, path in work:
        _run(owner, rule, path, emit)
    if held:
        emit(f"{len(_PENDING[owner])} yeni dosya bekliyor (saatlik {HOURLY_LIMIT} dosya sınırı). "
             "İşlemem için “bekleyen dosyaları işle” de.")


def _run(owner, rule, path, emit):
    try:
        emit(process(owner, rule, path))
    except ValueError as e:
        emit(f"{path.name}: {e}")
    except Exception:
        _record_failure('modules/watcher.py:process')
        emit(f"{path.name} işlenirken hata oldu; dosyayı sohbete ekleyip elle deneyebilirsin.")


def run_pending(owner: str) -> str:
    with _LOCK:
        items = _PENDING.pop(owner, [])
    if not items:
        return "Bekleyen dosya yok."
    out = []
    for rule, path in items[:20]:
        if path.is_file():
            _run(owner, rule, path, out.append)
    rest = items[20:]
    if rest:
        with _LOCK:
            _PENDING.setdefault(owner, [])[:0] = rest
    return "\n\n".join(out) + (f"\n\n{len(rest)} dosya daha bekliyor." if rest else "")



def _finance_price(kind, symbol):
    from modules import finance
    return finance.quote(kind, symbol)


def finance_tick(owner, emit, *, now=None, price_getter=None):
    from modules import finance_alert_tick
    return finance_alert_tick.tick(owner, emit, now=now, price_getter=price_getter)

def loop(runtime) -> None:
    """Arka plan döngüsü: yalnız PC'nin aktif kullanıcısının kuralları çalışır."""
    while not runtime.stop_event.wait(INTERVAL):
        try:
            owner = runtime.pc_profile()
            topic = (owner.data.get("prefs") or {}).get("ntfy_topic")

            def emit(text, o=owner):
                runtime._emit_for(o, "assistant", text, "izleme")
                if topic:   # telefon bildirimi açıksa kısa haber
                    runtime.notify.send(topic, "Jarvis klasör izleme", text.split("\n", 1)[0][:200])
            finance_tick(owner.slug, emit)
            if load(owner.slug):
                runtime._llm.set_user_context(owner.slug)       # bu iş parçacığında yalnız o kullanıcının anahtarı
                tick(owner.slug, emit)
        except Exception:
            _record_failure('modules/watcher.py:loop')
