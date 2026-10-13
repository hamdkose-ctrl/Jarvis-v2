"""Gmail ve Google Takvim (YALNIZCA OKUMA) + ev/iş devir listesi için Google Görevler (yalnız "Jarvis" listesi).

Kurulum (bir kez):
  1) https://console.cloud.google.com adresinde bir proje aç; "Gmail API" ve "Google Calendar API"yi etkinleştir.
  2) "OAuth izin ekranı"nı kur. Kalıcı kullanım için Google Auth Platform > Audience bölümünde In production yap.
     (Testing durumunda refresh token 7 gün sonra düşebilir.)
  3) "Kimlik bilgileri > OAuth istemci kimliği > Masaüstü uygulaması" oluştur, JSON'u indir.
  4) İndirdiğin dosyayı  ~/.jarvis/google_credentials.json  adıyla kaydet.
  5) python -m pip install google-api-python-client google-auth-oauthlib
İlk komutta tarayıcı açılır, izni sen onaylarsın; şifren Jarvis'e hiç verilmez. İzin dosyası ~/.jarvis/google_token.json.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import re
from datetime import datetime, timedelta

from config import DATA_DIR

CRED = DATA_DIR / "google_credentials.json"
TOKEN = DATA_DIR / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/calendar.readonly"]

SETUP_HELP = ("Google bağlantısı kurulu değil. Adımlar: Google Cloud Console'da proje aç, Gmail API ve Calendar API'yi "
              "etkinleştir, “Masaüstü uygulaması” türünde OAuth kimliği oluşturup JSON'u indir ve "
              f"{CRED} olarak kaydet; sonra terminalde: python -m pip install google-api-python-client google-auth-oauthlib")


# Google Görevler (ev/iş devir listesi) ayrı izinle tutulur: Gmail/Takvim izni bozulmasın, okuma izni yine salt-okuma kalsın.
TASKS_TOKEN = DATA_DIR / "google_tasks_token.json"
TASKS_SCOPES = ["https://www.googleapis.com/auth/tasks"]


import threading
_token_lock = threading.RLock()

def token_path(token=None):
    from modules import llm
    from config import load_settings, save_settings
    from modules.personalization import get_active, slugify
    user = llm.current_user()
    if not user:
        raise PermissionError("Google hesabı için kullanıcı seçilmeli.")
    legacy = token or TOKEN
    folder = DATA_DIR / "google_users" / user
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / legacy.name
    with _token_lock:
        if legacy.exists():
            owner = load_settings().get("google_legacy_owner")
            if not owner:
                owner = slugify(get_active())
                save_settings(google_legacy_owner=owner)
            if owner == user and not dest.exists():
                dest.write_bytes(legacy.read_bytes())
                legacy.unlink()
    return dest


def _creds(token=None, scopes=None, interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    token, scopes = token_path(token), scopes or SCOPES
    creds = Credentials.from_authorized_user_file(str(token), scopes) if token.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:          # noqa: BLE001 - izin süresi dolmuş/geri alınmış: yeniden izin iste
            _record_failure('modules/google_api.py:_creds')
            if not interactive or "invalid_grant" not in str(exc):
                raise
            token.unlink(missing_ok=True)
            creds = InstalledAppFlow.from_client_secrets_file(str(CRED), scopes).run_local_server(port=0)
            _mark_granted(token)
    elif interactive:
        creds = InstalledAppFlow.from_client_secrets_file(str(CRED), scopes).run_local_server(port=0)
        _mark_granted(token)
    else:
        raise PermissionError("izin yok")
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _mark_granted(token) -> None:
    """İzin ne zaman verildi? (Test modundaki Google uygulamalarında izin 7 gün sonra düşer; önceden uyarmak için.)"""
    import time
    from config import save_settings
    save_settings(**{f"granted_{token.stem}": int(time.time())})


def health() -> list[str]:
    """Google izinlerinin durumu: düşmüş ya da 1 gün içinde düşecek izinler için kullanıcıya söylenecek cümleler."""
    import time
    from config import load_settings
    out = []
    s = load_settings()
    production = bool(s.get("google_oauth_production", False))
    for legacy, scopes, label in ((TOKEN, SCOPES, "Gmail ve Takvim"), (TASKS_TOKEN, TASKS_SCOPES, "Görevler (devir listesi)")):
        token = token_path(legacy)
        if not token.exists():
            continue
        try:
            _creds(token, scopes, interactive=False)
        except Exception as exc:          # noqa: BLE001
            _record_failure('modules/google_api.py:health')
            if "invalid_grant" in str(exc) or isinstance(exc, PermissionError):
                out.append(f"Google {label} izninin süresi doldu. Entegrasyonlar sayfasında "
                           + ("“Bağlan / dene”" if token == TOKEN else "“Görevler iznini ver”") + " düğmesine basıp yenile.")
            continue                      # internet yok vb.: sessiz geç
        if production:
            continue                      # Production yayın durumunda 7 günlük Testing uyarısı geçerli değildir.
        granted = s.get(f"granted_{token.stem}")
        if not granted:                   # bu özellikten önce verilmiş izin: bugün verilmiş say
            _mark_granted(token)
            continue
        if time.time() - granted > 6 * 86400:
            out.append(f"Google {label} izni yarın bitiyor. Şimdi Entegrasyonlar'dan "
                       + ("“Bağlan / dene”" if token == TOKEN else "“Görevler iznini ver”") + " düğmesine basarsan bir hafta daha sorun çıkmaz.")
    return out


def _service(name: str, version: str, interactive: bool = False):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_creds(interactive=interactive), cache_discovery=False)


def tasks_service(interactive: bool = False):
    """Google Görevler. interactive=False iken izin yoksa PermissionError (arka planda tarayıcı açılmasın)."""
    from googleapiclient.discovery import build
    return build("tasks", "v1", credentials=_creds(TASKS_TOKEN, TASKS_SCOPES, interactive), cache_discovery=False)


def _ready() -> str | None:
    """Kullanıma hazırsa None, değilse kullanıcıya söylenecek açıklama."""
    if not CRED.exists() and not token_path().exists():
        return SETUP_HELP
    try:
        import googleapiclient, google_auth_oauthlib   # noqa: F401
    except ImportError:
        return "Google paketleri eksik: python -m pip install google-api-python-client google-auth-oauthlib"
    return None


def connect() -> tuple[bool, str]:
    """Ayarlar sayfasındaki 'Bağlan' için: izni alır ve takvime bir kez bakar. (başarılı mı, açıklama)"""
    if not CRED.exists() and not token_path().exists():
        return False, "Önce JSON dosyasını seç."
    try:
        import googleapiclient, google_auth_oauthlib   # noqa: F401
    except ImportError:
        return False, ("Google paketleri kurulu değil. Terminalde (VS Code'da .venv açıkken) çalıştır: "
                       "python -m pip install google-api-python-client google-auth-oauthlib")
    try:
        svc = _service("calendar", "v3", interactive=True)     # izin süresi dolduysa tarayıcıda yeniden ister
        svc.calendarList().list(maxResults=1).execute()
        return True, "Bağlantı kuruldu ✓  Artık “okunmamış mailleri oku” ya da “bugün ajandamda ne var” diyebilirsin."
    except Exception as exc:      # noqa: BLE001
        _record_failure('modules/google_api.py:connect')
        text = f"{type(exc).__name__}: {exc}"
        if "access_denied" in text or "403" in text:
            text += "  (OAuth izin ekranında kendi e-postanı “test kullanıcısı” olarak eklediğinden ve Gmail/Calendar API'lerin açık olduğundan emin ol.)"
        return False, text[:400]


def _friendly(exc: Exception, what: str) -> str:
    t = f"{type(exc).__name__}: {exc}"
    if "invalid_grant" in t or isinstance(exc, PermissionError) or "expired" in t.lower():
        return (f"{what}: Google izninin süresi dolmuş. Entegrasyonlar → Gmail ve Google Takvim → "
                "“Bağlan / dene”ye basıp izni yenile.")
    return f"{what}: {t}"


def unread_mail(limit: int = 5) -> str:
    problem = _ready()
    if problem:
        return problem
    try:
        svc = _service("gmail", "v1")
        total = svc.users().labels().get(userId="me", id="INBOX").execute().get("messagesUnread", 0)
        if not total:
            return "Okunmamış e-postan yok."
        ids = svc.users().messages().list(userId="me", q="is:unread in:inbox", maxResults=limit).execute() \
            .get("messages", [])
        lines = []
        for m in ids:
            msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                             metadataHeaders=["From", "Subject"]).execute()
            h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
            sender = re.sub(r"\s*<.*?>", "", h.get("From", "")).strip(' "') or "Bilinmeyen"
            lines.append(f"{sender}: {h.get('Subject', '(konusuz)')}")
        more = f" (ilk {len(lines)} tanesi)" if total > len(lines) else ""
        return f"{total} okunmamış e-postan var{more}: " + "; ".join(lines) + "."
    except Exception as exc:
        _record_failure('modules/google_api.py:unread_mail')
        return _friendly(exc, "E-postalara bakamadım")


def agenda(day_offset: int = 0, label: str = "Bugün") -> str:
    problem = _ready()
    if problem:
        return problem
    try:
        svc = _service("calendar", "v3")
        start = (datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                 + timedelta(days=day_offset))
        end = start + timedelta(days=1)
        items = svc.events().list(calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
                                  singleEvents=True, orderBy="startTime", maxResults=15).execute().get("items", [])
        if not items:
            return f"{label} Google Takvim'inde etkinlik yok."
        parts = []
        for e in items:
            when = e["start"].get("dateTime")
            hhmm = datetime.fromisoformat(when).strftime("%H:%M") + " " if when else ""
            parts.append(hhmm + e.get("summary", "(adsız)"))
        return f"{label} Google Takvim'inde: " + "; ".join(parts) + "."
    except Exception as exc:
        _record_failure('modules/google_api.py:agenda')
        return _friendly(exc, "Takvime bakamadım")


_MAIL = r"(?:g?mail|e-?posta|eposta|ileti)['’]?\w*"
# "maili kontrol et", "maillerime bak", "mail geldi mi", "gmail'e bak", "okunmamış e-postalar" ...
_MAIL_CHECK = re.compile(
    rf"okunmamış|gelen kutu|yeni {_MAIL}|"
    rf"{_MAIL}\s+(?:\w+\s+)?(?:k\w{{0,2}}t\w{{0,2}}r\w{{0,2}}l|bak|oku|var\s*mı|geldi|gelmiş|neler|ne var|kaç)|"
    rf"(?:kontrol et|bak|oku)\w*\s+{_MAIL}")
_MAIL_SEND = re.compile(r"\b(?:gönder|yaz|at|ilet)\w*\b(?!.*\b(?:kontrol|bak)\w*)")


def handle(cmd_lower: str) -> str | None:
    t = cmd_lower
    if _MAIL_CHECK.search(t) and not _MAIL_SEND.search(t):
        return unread_mail()
    if re.search(r"toplantı|google takvim", t) and not re.search(r"ekle|hatırlat|sil\b", t):
        if "yarın" in t:
            return agenda(1, "Yarın")
        return agenda(0, "Bugün")
    return None
