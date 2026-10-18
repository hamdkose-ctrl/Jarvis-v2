"""İş e-postası: bilgisayarda açık olan (klasik) Outlook uygulamasından okunmamış mailleri okur.

Outlook kapalıysa arka planda açılır. Yalnızca okur; göndermez, silmez, okundu işaretlemez. Gönderen ve konu bu bilgisayarda kalır, yapay zekaya gönderilmez.
Microsoft hesabı ya da uygulama kaydı gerekmez: Windows'un COM arayüzü kullanılır (comtypes zaten kurulu).
"""
from modules.diagnostics import record_failure as _record_failure
import re
import sys
import time

_MAIL = r"(?:g?mail|e-?posta|eposta|ileti)['’]?\w*"
_WORK = re.compile(r"\b(?:iş|işyeri|şirket|ofis)\w*\s+(?:(?:önemli|öncelikli|acil|yeni|okunmamış)\w*\s+)?" + _MAIL + r"|outlook\w*")
IMPORTANT_NOTE = "Outlook'ta önem derecesine bakmıyorum; okunmamış iş maillerin: "
_RANK = re.compile(r"önemli|öncelikli|acil")
_CHECK = re.compile(r"k\w{0,2}t\w{0,2}r\w{0,2}l|bak|oku|var\s*mı|geldi|gelmiş|neler|ne var|kaç|okunmamış|yeni|göster|söyle")   # "kotrol" gibi yazım hataları da


def running() -> bool:
    """Outlook şu an açık mı (kapalıysa açılınca biraz beklenir)."""
    try:
        import psutil
        return any((p.info.get("name") or "").lower() == "outlook.exe" for p in psutil.process_iter(["name"]))
    except Exception:
        _record_failure('modules/outlook.py:running')
        return False


def installed() -> bool:
    """Bilgisayarda Outlook kurulu mu (evdeki bilgisayarda olmayabilir)."""
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Outlook.Application"))
        return True
    except (OSError, ImportError):
        return False


def _launch() -> None:
    """Outlook'u normal penceresiyle açar (kullanıcı açıldığını görsün)."""
    import subprocess
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "outlook.exe"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass
    for _ in range(20):
        if running():
            break
        time.sleep(0.5)
    time.sleep(4)                         # profil ve gelen kutusu yüklensin


def _inbox():
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitialize()          # Jarvis komutları ayrı bir iş parçacığında çalışır
    except OSError:
        pass
    try:
        app = comtypes.client.GetActiveObject("Outlook.Application", dynamic=True)
    except OSError:
        app = comtypes.client.CreateObject("Outlook.Application", dynamic=True)
    return app.GetNamespace("MAPI").GetDefaultFolder(6)      # 6 = Gelen Kutusu


def unread_mail(limit: int = 5, prefix: str = "") -> str:
    if not sys.platform.startswith("win") or not installed():
        return "Bu bilgisayarda Outlook kurulu değil."
    was_running = running()
    if not was_running:
        _launch()
    try:
        inbox = None
        for _ in range(15):               # Outlook kapalıysa açılır; profilin yüklenmesini bekle
            try:
                inbox = _inbox()
                break
            except Exception:
                _record_failure('modules/outlook.py:unread_mail')
                if not was_running:
                    time.sleep(2)
                    continue
                raise
        if inbox is None:
            return prefix + "Outlook'u açtım ama henüz hazır değil, birazdan tekrar sor."
        if not was_running:
            time.sleep(3)                 # yeni açıldıysa sunucuyla eşitlemeye kısa süre tanı
        items = inbox.Items.Restrict("[UnRead] = True")
        total = int(items.Count)
        if not total:
            return prefix + "Okunmamış iş mailin yok."
        items.Sort("[ReceivedTime]", True)
        lines = []
        for i in range(1, min(total, limit) + 1):
            it = items.Item(i)
            try:
                sender = str(it.SenderName or "").strip() or "Bilinmeyen"
                subject = str(it.Subject or "").strip() or "(konusuz)"
            except Exception:
                _record_failure('modules/outlook.py:unread_mail')
                continue          # toplantı daveti gibi farklı türler
            subject = re.sub(r"^(?:(?:re|fw|fwd|ynt|ilt)\s*:\s*)+", "", subject, flags=re.I)
            lines.append(f"{sender}: {subject}")
        more = f" (en yeni {len(lines)} tanesi)" if total > len(lines) else ""
        return prefix + f"{total} okunmamış iş mailin var{more}: " + "; ".join(lines) + "."
    except Exception as exc:
        _record_failure('modules/outlook.py:unread_mail')
        return prefix + f"Outlook'a bakamadım: {type(exc).__name__}: {exc}"


def handle(cmd_lower: str) -> str | None:
    """'iş maillerimi kontrol et', 'outlook'a bak', 'outlook'ta yeni mail var mı' gibi istekler."""
    t = cmd_lower
    if re.search(r"\b(?:gönder|yaz|at)\w*\b", t) and not re.search(r"kontrol|bak", t):
        return None
    if _WORK.search(t) and (_CHECK.search(t) or len(t.split()) <= 3):   # "iş maili", "outlook mailleri"
        if re.fullmatch(r"\s*outlook\w*['’]?\w*\s+(?:aç|başlat|çalıştır)\w*\s*", t):
            return None
        return unread_mail(prefix=IMPORTANT_NOTE if _RANK.search(t) else "")
    return None
