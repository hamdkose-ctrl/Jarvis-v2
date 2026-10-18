"""Gmail ve Google Takvim (YALNIZCA OKUMA) + ev/iş devir listesi için Google Görevler (yalnız "Jarvis" listesi).

Kurulum (bir kez):
  1) https://console.cloud.google.com adresinde bir proje aç; "Gmail API" ve "Google Calendar API"yi etkinleştir.
  2) "OAuth izin ekranı"nı kur. Kalıcı kullanım için Google Auth Platform > Audience bölümünde In production yap.
     (Testing durumunda Google refresh token'ı bir süre sonra iptal edebilir; Jarvis kesin süre söylemez.)
  3) "Kimlik bilgileri > OAuth istemci kimliği > Masaüstü uygulaması" oluştur, JSON'u indir.
  4) İndirdiğin dosyayı  ~/.jarvis/google_credentials.json  adıyla kaydet.
  5) python -m pip install google-api-python-client google-auth-oauthlib
İlk komutta tarayıcı açılır, izni sen onaylarsın; şifren Jarvis'e hiç verilmez. İzin dosyası ~/.jarvis/google_token.json.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _diagnostic_failure

import re
from datetime import datetime, timedelta


def _record_failure(context, *, credential_error=False):
    if not credential_error:
        return _diagnostic_failure(context)
    # Never let diagnostics inspect credential parser/refresh messages or URLs.
    import sys
    kind = sys.exc_info()[0]
    try:
        raise RuntimeError('Google kimlik işlemi başarısız: ' + (kind.__name__ if kind else 'Exception')) from None
    except RuntimeError:
        _diagnostic_failure(context)

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
    from modules.publish_services import _credential_path, _read_private_json, _write_private_json
    _credential_path(folder / legacy.name)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / legacy.name
    with _token_lock:
        if legacy.exists():
            owner = load_settings().get("google_legacy_owner")
            if not owner:
                owner = slugify(get_active())
                save_settings(google_legacy_owner=owner)
            if owner == user and not dest.exists():
                try:
                    # Do not modify the only legacy copy until the destination
                    # has a verified, atomically committed protected credential.
                    data, original = _read_private_json(legacy, migrate=False, with_snapshot=True)
                    _write_private_json(dest, data, expected=None)
                except Exception:
                    _record_failure('modules/google_api.py:token_migration', credential_error=True)
                    return legacy  # Includes malformed legacy data: never delete it.
                try:
                    if legacy.read_bytes() == original:
                        legacy.unlink()
                except OSError: pass
    return dest


def _creds(token=None, scopes=None, interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from modules.publish_services import _read_private_json, _write_private_json, _LOGIN_REQUIRED
    token, scopes = token_path(token), scopes or SCOPES
    try:
        info, expected = _read_private_json(token, with_snapshot=True) if token.exists() else (None, None)
    except (ValueError, PermissionError):
        raise PermissionError(_LOGIN_REQUIRED) from None
    try:
        creds = Credentials.from_authorized_user_info(info, scopes) if info is not None else None
    except Exception:
        _record_failure('modules/google_api.py:credential_parse', credential_error=True)
        raise PermissionError(_LOGIN_REQUIRED) from None
    if creds and creds.valid:
        return creds
    granted = False
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:          # noqa: BLE001 - izin süresi dolmuş/geri alınmış: yeniden izin iste
            _record_failure('modules/google_api.py:credential_refresh', credential_error=True)
            if not interactive or "invalid_grant" not in str(exc):
                raise PermissionError(_LOGIN_REQUIRED) from None
            # Failed re-login must not remove the user's existing credential.
            try:
                creds = InstalledAppFlow.from_client_secrets_file(str(CRED), scopes).run_local_server(port=0)
            except Exception:
                _record_failure('modules/google_api.py:credential_reconnect', credential_error=True)
                raise PermissionError(_LOGIN_REQUIRED) from None
            granted = True
    elif interactive:
        try:
            creds = InstalledAppFlow.from_client_secrets_file(str(CRED), scopes).run_local_server(port=0)
        except Exception:
            _record_failure('modules/google_api.py:credential_connect', credential_error=True)
            raise PermissionError(_LOGIN_REQUIRED) from None
        granted = True
    else:
        raise PermissionError(_LOGIN_REQUIRED)
    try:
        import json
        _write_private_json(token, json.loads(creds.to_json()), expected=expected)
    except Exception:
        _record_failure('modules/google_api.py:credential_save', credential_error=True)
        return creds  # Keep working with refreshed in-memory credentials; old disk bytes survive.
    if granted:
        try: _mark_granted(token)
        except Exception:
            _record_failure('modules/google_api.py:credential_grant_age', credential_error=True)
            pass  # Grant-age bookkeeping must not lose a successful login.
    return creds


# Uyarılarda gösterilecek yer ve her iznin KENDİ düğmesi (Gmail/Takvim ile Görevler ayrı izin dosyasıdır).
PLACE = "Menü › Yapay zekâ › Gmail ve Takvim"
BUTTONS = {"google_token": "Bağlan", "google_tasks_token": "Görevler iznini ver"}


def _grant_key(token) -> str:
    """İzin zamanı kullanıcıya özeldir (google_users/<kullanıcı>/...); eski ortak anahtar başka kullanıcıya taşınmaz."""
    return f"granted_{token.parent.name}_{token.stem}"


def _mark_granted(token) -> None:
    """İzin ne zaman verildi? Yalnız bilgi içindir: Google gerçek bitiş zamanını bildirmez."""
    import time
    from config import save_settings
    save_settings(**{_grant_key(token): int(time.time())})


def health() -> list[str]:
    """Google izinlerinin durumu: çalışmayan ya da Testing modunda eskiyen izinler için kullanıcıya söylenecek cümleler.

    Kesin süre sözü verilmez: izin yalnız şu an yenilenip yenilenemediğiyle sınanır; Google bitiş zamanını bildirmez."""
    import time
    from config import load_settings
    out = []
    s = load_settings()
    production = bool(s.get("google_oauth_production", False))
    for legacy, scopes, label in ((TOKEN, SCOPES, "Gmail ve Takvim"), (TASKS_TOKEN, TASKS_SCOPES, "Görevler (devir listesi)")):
        token = token_path(legacy)
        button = BUTTONS[legacy.stem]       # kullanıcıya özel yol eski TOKEN ile eşit değildir; izni adından seç
        if not token.exists():
            continue
        try:
            _creds(token, scopes, interactive=False)
        except Exception as exc:          # noqa: BLE001
            _record_failure('modules/google_api.py:health')
            if "invalid_grant" in str(exc) or isinstance(exc, PermissionError):
                out.append(f"Google {label} izni artık çalışmıyor (süresi dolmuş ya da geri alınmış). "
                           f"{PLACE} bölümünde “{button}” düğmesine basıp izni yenile.")
            continue                      # internet yok vb.: sessiz geç
        if production:
            continue                      # Production yayın durumunda Testing uyarısı geçerli değildir.
        key = _grant_key(token)
        granted = s.get(key)
        if not granted:                   # bu özellikten önce verilmiş izin: bugün verilmiş say
            _mark_granted(token)
            continue
        days = int((time.time() - granted) // 86400)
        if days >= 6:
            out.append(f"Google {label} izni şu an çalışıyor; {days} gün önce verildi. Google uygulaman Testing "
                       "modundaysa Google bu izni bir süre sonra kaldırabilir, ne zaman kaldıracağı buradan "
                       f"doğrulanamıyor. İzin düşerse {PLACE} bölümündeki “{button}” düğmesiyle yeniden bağlanırsın; "
                       "kalıcı çözüm Google Cloud'da uygulamayı In production yapmaktır.")
    return out


def _service(name: str, version: str, interactive: bool = False):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_creds(interactive=interactive), cache_discovery=False)


def tasks_service(interactive: bool = False):
    """Google Görevler. interactive=False iken izin yoksa PermissionError (arka planda tarayıcı açılmasın)."""
    from googleapiclient.discovery import build
    return build("tasks", "v1", credentials=_creds(TASKS_TOKEN, TASKS_SCOPES, interactive), cache_discovery=False)


def connected() -> bool:
    """Bu kullanıcının Gmail/Takvim izni kayıtlı mı? Eski ortak TOKEN bağlanınca kullanıcı klasörüne taşınıp
    silinir; ona bakan kod bağlıyken bile "bağlı değil" sanıyordu (sabah özeti maili/takvimi atlıyordu)."""
    try:
        return token_path().exists()
    except PermissionError:               # kullanıcı seçilmemiş
        return False


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


def needs_reconnect(exc: Exception) -> bool:
    """İzin süresi dolmuş/geri alınmış ya da hiç verilmemiş mi (ağ hatası değil)?"""
    t = f"{type(exc).__name__}: {exc}"
    return "invalid_grant" in t or isinstance(exc, PermissionError) or "expired" in t.lower()


def reconnect_help() -> str:
    return (f"Google izni çalışmıyor (süresi dolmuş ya da geri alınmış). {PLACE} bölümünde "
            "“Bağlan” düğmesine basıp izni yenile.")


def _friendly(exc: Exception, what: str) -> str:
    t = f"{type(exc).__name__}: {exc}"
    if needs_reconnect(exc):
        return (f"{what}: Google izni çalışmıyor (süresi dolmuş ya da geri alınmış). {PLACE} bölümünde "
                "“Bağlan” düğmesine basıp izni yenile.")
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


def day_events(day_offset: int = 0) -> list[tuple[datetime | None, str]]:
    """O günün Google Takvim etkinlikleri, (başlangıç ya da tüm gün için None, ad). Hata yukarı fırlatılır."""
    svc = _service("calendar", "v3")
    start = (datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
             + timedelta(days=day_offset))
    items = svc.events().list(calendarId="primary", timeMin=start.isoformat(),
                              timeMax=(start + timedelta(days=1)).isoformat(), singleEvents=True,
                              orderBy="startTime", maxResults=25).execute().get("items", [])
    out = []
    for e in items:
        when = e.get("start", {}).get("dateTime")
        out.append((datetime.fromisoformat(when) if when else None, e.get("summary") or "(adsız)"))
    return out


def range_events(start_offset: int, days: int) -> list[tuple]:
    """[bugün+start_offset, +days) aralığının Google Takvim etkinlikleri: (gün, başlangıç ya da tüm gün için None, ad).
    Tek çağrı; çok günlük tüm gün etkinliği yalnız ilk gününde görünür. Hata yukarı fırlatılır."""
    svc = _service("calendar", "v3")
    start = (datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
             + timedelta(days=start_offset))
    items = svc.events().list(calendarId="primary", timeMin=start.isoformat(),
                              timeMax=(start + timedelta(days=days)).isoformat(), singleEvents=True,
                              orderBy="startTime", maxResults=100).execute().get("items", [])
    out = []
    for e in items:
        st = e.get("start", {})
        if st.get("dateTime"):
            when = datetime.fromisoformat(st["dateTime"]).astimezone()
            out.append((when.date(), when, e.get("summary") or "(adsız)"))
        elif st.get("date"):
            out.append((datetime.fromisoformat(st["date"]).date(), None, e.get("summary") or "(adsız)"))
    return out


def unread_count() -> int:
    """Gelen kutusundaki okunmamış mail sayısı (yalnız sayı; içerik okunmaz). Hata yukarı fırlatılır."""
    svc = _service("gmail", "v1")
    return int(svc.users().labels().get(userId="me", id="INBOX").execute().get("messagesUnread", 0))


def busy_between(start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    """Google Takvim'de [start, end) aralığıyla kesişen saatli etkinlikler (salt okuma, çakışma uyarısı için).

    Bağlı değilse ya da okunamazsa boş liste: çakışma sorusu yalnız bir uyarıdır, kaydı engellemez."""
    if not connected() or _ready() is not None:
        return []
    try:
        start, end = start.astimezone(), end.astimezone()
        items = _service("calendar", "v3").events().list(
            calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True,
            orderBy="startTime", maxResults=10).execute().get("items", [])
    except Exception:
        _record_failure('modules/google_api.py:busy_between')
        return []
    out = []
    for e in items:
        a, b = e.get("start", {}).get("dateTime"), e.get("end", {}).get("dateTime")
        if not a or not b:                # tüm gün etkinlik: saat çakışması sayılmaz
            continue
        a, b = datetime.fromisoformat(a), datetime.fromisoformat(b)
        if a < end and b > start:
            out.append((a, b, e.get("summary") or "(adsız)"))
    return out


_ROBOT = re.compile(r"no-?reply|noreply|do-?not-?reply|bildirim|notification|mailer-daemon|newsletter|bulten|bülten", re.I)


def _addr(header: str) -> str:
    m = re.search(r"<([^>]+)>", header or "")
    return (m.group(1) if m else (header or "")).strip().lower()


def _addrs(header: str) -> set[str]:
    """To/Cc başlığındaki tam adresler (küçük harf). "Köse, Hamdi" <a@b.com> gibi virgüllü adlar bölünmez."""
    from email.utils import getaddresses
    return {a.strip().lower() for _n, a in getaddresses([header or ""]) if a}


def _name(header: str) -> str:
    return re.sub(r"\s*<.*?>", "", header or "").strip(' "') or _addr(header) or "Bilinmeyen"


def awaiting(kind: str, limit: int = 8, info: dict | None = None) -> list[dict]:
    """Cevap takibi, yalnız zarf bilgisiyle (gövde okunmaz).

    kind="mine": son yedi günde doğrudan sana (To) yazılmış, kişi gönderen, son mesajı senden olmayan konuşmalar.
    kind="theirs": son 30 günde senin gönderip en az 2 gündür cevap gelmeyen konuşmalar (son mesaj senin).
    `info` verilirse taranan konuşma sayısı ("scanned"), Gmail'in 20'lik sayfasının dolup dolmadığı ("capped") ve
    sınırdan dolayı kesilip kesilmediği ("cut") yazılır; böylece boş sonuç "hiç yok" gibi sunulmaz.
    Hata yukarı fırlatılır."""
    svc = _service("gmail", "v1")
    me = svc.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
    q = ("in:inbox newer_than:7d -category:promotions -category:social -category:updates -category:forums -from:me"
         if kind == "mine" else "in:sent newer_than:30d older_than:2d")
    threads = svc.users().threads().list(userId="me", q=q, maxResults=20).execute().get("threads", [])
    out, now = [], datetime.now().astimezone()
    if info is not None:
        info.update(scanned=len(threads), capped=len(threads) >= 20, cut=False)
    for th in threads:
        if len(out) >= limit:
            if info is not None:
                info["cut"] = True            # sınıra ulaşıldı, daha fazlası olabilir
            break
        msgs = svc.users().threads().get(userId="me", id=th["id"], format="metadata",
                                         metadataHeaders=["From", "To", "Subject"]).execute().get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        h = {x["name"]: x["value"] for x in last.get("payload", {}).get("headers", [])}
        mine_last = "SENT" in last.get("labelIds", []) or _addr(h.get("From", "")) == me
        if kind == "mine":
            if mine_last or _ROBOT.search(h.get("From", "")) or (me and me not in _addrs(h.get("To", ""))):
                continue
            who = _name(h.get("From", ""))
        else:
            if not mine_last:
                continue
            who = _name(h.get("To", "").split(",")[0])
        when = datetime.fromtimestamp(int(last.get("internalDate", 0)) / 1000).astimezone()
        if kind == "theirs" and now - when < timedelta(days=2):
            continue                      # sorgu konuşma düzeyinde: son mesaj (ör. dünkü takibim) yeniyse bekleyen sayılmaz
        out.append({"who": who, "subject": h.get("Subject") or "(konusuz)", "days": max((now - when).days, 0)})
    return out


def important(limit: int = 6) -> list[dict]:
    """Okunmamış gelen kutusunda Gmail'in "önemli" veya yıldız işaretlediği kişi mailleri (zarf; gövde okunmaz).

    Yıldızlılar önce gelir. Robot/bildirim göndericiler ve promosyon/sosyal/forum kategorileri hariçtir.
    Hata yukarı fırlatılır."""
    svc = _service("gmail", "v1")
    q = "is:unread in:inbox (is:important OR is:starred) -category:promotions -category:social -category:forums"
    ids = svc.users().messages().list(userId="me", q=q, maxResults=20).execute().get("messages", [])
    out = []
    for m in ids:
        msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                         metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
        if _ROBOT.search(h.get("From", "")):
            continue
        out.append({"who": _name(h.get("From", "")), "subject": h.get("Subject") or "(konusuz)",
                    "starred": "STARRED" in msg.get("labelIds", [])})
    out.sort(key=lambda x: not x["starred"])
    return out[:limit]


def search_mail(keywords: list[str], days: int = 30, limit: int = 5) -> list[dict]:
    """Son `days` günde konu/gönderen/gövdesinde anahtar sözcüklerden biri geçen kişi mailleri, yalnız zarf (gövde okunmaz):
    {who, subject, days}. Promosyon/sosyal/forum ve robot göndericiler hariç. Hata yukarı fırlatılır."""
    words = [re.sub(r"[^\w-]", "", w) for w in keywords]
    words = [w for w in words if w]
    if not words:
        return []
    svc = _service("gmail", "v1")
    q = f"newer_than:{int(days)}d ({' OR '.join(words)}) -category:promotions -category:social -category:forums"
    ids = svc.users().messages().list(userId="me", q=q, maxResults=15).execute().get("messages", [])
    out, now = [], datetime.now().astimezone()
    for m in ids:
        if len(out) >= limit:
            break
        msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                         metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
        if _ROBOT.search(h.get("From", "")):
            continue
        when = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000).astimezone()
        out.append({"who": _name(h.get("From", "")), "subject": h.get("Subject") or "(konusuz)",
                    "days": max((now - when).days, 0)})
    return out


def important_text() -> str:
    problem = _ready()
    if problem:
        return problem
    try:
        items = important()
    except Exception as exc:
        _record_failure('modules/google_api.py:important_text')
        return _friendly(exc, "Önemli maillere bakamadım")
    if not items:
        return "Okunmamış önemli mailin görünmüyor (Gmail'in önemli/yıldız işaretlerine göre)."
    return (f"Okunmamış {len(items)} önemli mailin var (Gmail'in önemli/yıldız işaretine göre): "
            + "; ".join(f"{x['who']}{' ★' if x['starred'] else ''}: {x['subject']}" for x in items) + ".")


def awaiting_text(kind: str) -> str:
    problem = _ready()
    if problem:
        return problem
    info: dict = {}
    try:
        items = awaiting(kind, info=info)
    except Exception as exc:
        _record_failure('modules/google_api.py:awaiting_text')
        return _friendly(exc, "Cevap bekleyen maillere bakamadım")
    ago = lambda d: "bugün" if d == 0 else f"{d} gün önce"
    if kind == "mine":
        if not items:
            return ("Son bir haftada kişilerden gelip cevaplamadığın mail görmedim (Gmail)." + _scan_note(info, False))
        return (f"Cevap vermediğin {len(items)} mail var (Gmail, son 7 gün): "
                + "; ".join(f"{x['who']} ({ago(x['days'])}): {x['subject']}" for x in items) + "." + _scan_note(info, True))
    if not items:
        return "Gönderip cevap bekleyen mailin yok (Gmail, son 30 gün)." + _scan_note(info, False)
    return (f"Cevap gelmeyen {len(items)} mailin var (Gmail): "
            + "; ".join(f"{x['who']}, {ago(x['days'])}: {x['subject']}" for x in items) + "." + _scan_note(info, True))


def _scan_note(info: dict, shown: bool) -> str:
    """Tarama sınırlıysa söyler: Gmail'den en çok 20 konuşma alınır, cevapta en çok 8 mail gösterilir."""
    if info.get("cut"):
        return f" İlk 8 tanesini gösterdim; daha fazlası olabilir."
    if info.get("capped"):
        return f" Yalnız en yeni {info['scanned']} konuşmaya baktım; daha eskilere bakmadım."
    return ""


# "cevap vermediğim mailler", "cevaplamadığım mailler" (bana gelen) / "cevap gelmeyen maillerim" (benim gönderdiğim)
_AWAIT_THEIRS = re.compile(r"cevap\w*\s+(?:gelmeyen|gelmedi|dönmeyen|dönmedi|bekledi[ğg]im|bekliyorum)|"
                           r"(?:yanıt|dönüş)\w*\s+(?:gelmeyen|gelmedi|bekledi[ğg]im|bekliyorum)|dönüş yapmayan")
_AWAIT_MINE = re.compile(r"cevap\w*\s+(?:vermedi\w*|bekleyen)|cevaplamadı\w*|yanıtlamadı\w*|yanıt\w*\s+vermedi\w*|"
                         r"dönmediğim|dönüş yapmadığım")


_IMPORTANT = re.compile(r"(?:önemli|öncelikli|acil)\w*\s+(?:\w+\s+)?(?:g?mail|e-?posta|eposta)\w*|"
                        r"(?:g?mail|e-?posta|eposta)\w*\s+(?:\w+\s+)?(?:önemli|öncelikli|acil)\w*|"
                        r"hangi (?:g?mail|e-?posta|eposta)\w*\s+(?:\w+\s+)?önemli")


_MAIL = r"(?:g?mail|e-?posta|eposta|ileti)['’]?\w*"
# "maili kontrol et", "maillerime bak", "mail geldi mi", "gmail'e bak", "okunmamış e-postalar" ...
_MAIL_CHECK = re.compile(
    rf"okunmamış|gelen kutu|yeni {_MAIL}|"
    rf"{_MAIL}\s+(?:\w+\s+)?(?:k\w{{0,2}}t\w{{0,2}}r\w{{0,2}}l|bak|oku|var\s*mı|geldi|gelmiş|neler|ne var|kaç)|"
    rf"{_MAIL}\s+(?:göz at|göster|listele)|"
    rf"(?:kontrol et|bak|oku)\w*\s+{_MAIL}")
_MAIL_SEND = re.compile(r"\b(?:gönder|yaz|(?<!göz )at|ilet)\w*\b(?!.*\b(?:kontrol|bak)\w*)")


# "cevap vermediğim maillere cevap yaz/gönder/cevapla": liste değil, yazma isteğidir (Jarvis burada mail yazmaz/göndermez)
_AWAIT_REPLY = re.compile(r"\bcevap\s+(?:yaz|gönder|at|ver)(?!m[ae]d)\w*|\b(?:cevapla|yanıtla)(?!ma)\w*|\byanıt\s+(?:yaz|gönder)\w*")


def is_mail_query(t: str) -> bool:
    """handle() mail/özet cümlesini kendisi yanıtlayacak mı? (soru bekleyen hedefin bunu yutmaması için)"""
    if re.search(_MAIL, t) and not _AWAIT_REPLY.search(t) and (_AWAIT_THEIRS.search(t) or _AWAIT_MINE.search(t)):
        return True
    return bool((_IMPORTANT.search(t) or _MAIL_CHECK.search(t)) and not _MAIL_SEND.search(t))


def handle(cmd_lower: str) -> str | None:
    t = cmd_lower
    if (re.search(_MAIL, t) or re.search(r"\bkime\b|\bkimden\b|\bkimler\b", t)) and not _AWAIT_REPLY.search(t):
        if _AWAIT_THEIRS.search(t):
            return awaiting_text("theirs")
        if _AWAIT_MINE.search(t):
            return awaiting_text("mine")
    if _IMPORTANT.search(t) and not _MAIL_SEND.search(t):
        return important_text()
    if _MAIL_CHECK.search(t) and not _MAIL_SEND.search(t):
        return unread_mail()
    if re.search(r"toplantı|google takvim", t) and not re.search(r"ekle|hatırlat|sil\b", t):
        if "yarın" in t:
            return agenda(1, "Yarın")
        return agenda(0, "Bugün")
    return None
