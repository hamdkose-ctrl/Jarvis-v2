"""Google bağlantısı için adım adım kurulum (her kullanıcı kendi Google Cloud projesini açar).

Burası yalnız anlatır ve doğrulanabilenleri denetler: Google Cloud'daki tıklamalar kullanıcıdadır, Jarvis onları
göremez. Adımlar sabit https://console.cloud.google.com/ adreslerini açar; istemci dosyasındaki gizli değerler hiçbir
yanıta girmez. Takvime yazma izni bilerek yoktur (ayrı adım olarak sonra eklenecek).
"""
import importlib.util
import json

_C = "https://console.cloud.google.com/"

_STEPS = [
    {"id": "proje", "title": "Google Cloud'da proje aç",
     "text": "Google hesabınla gir, “Yeni proje” de ve adına Jarvis yaz.", "url": _C + "projectcreate"},
    {"id": "gmail", "title": "Gmail API'yi etkinleştir",
     "text": "Açılan sayfada “Etkinleştir” düğmesine bas.", "url": _C + "apis/library/gmail.googleapis.com"},
    {"id": "takvim", "title": "Google Calendar API'yi etkinleştir",
     "text": "Aynı şekilde “Etkinleştir” düğmesine bas.", "url": _C + "apis/library/calendar-json.googleapis.com"},
    {"id": "gorevler", "title": "Google Tasks API'yi etkinleştir (isteğe bağlı)", "optional": True,
     "text": "Yalnız ev/iş devir listesini kullanacaksan gerekir.", "url": _C + "apis/library/tasks.googleapis.com"},
    {"id": "izin", "title": "İzin ekranını kur",
     "text": "Başlayın de, uygulama adına Jarvis yaz, kendi e-postanı seç. Kitle: Harici (External). "
             "Kendi e-posta adresini test kullanıcısı olarak ekle.", "url": _C + "auth/overview"},
    {"id": "yayin", "title": "Uygulamayı yayına al (In production)",
     "text": "Hedef kitle (Audience) sayfasında “Uygulamayı yayınla” de ve In production yap; yapmazsan izin 7 günde "
             "düşer. Bağlanırken “Google bu uygulamayı doğrulamadı” uyarısı çıkarsa Gelişmiş › Jarvis'e git (güvenli değil) "
             "de: uygulamayı sen yaptın, yalnız kendi hesabına bağlanır.", "url": _C + "auth/audience"},
    {"id": "istemci", "title": "OAuth istemci kimliği oluştur ve indir",
     "text": "Kimlik bilgileri › Kimlik bilgisi oluştur › OAuth istemci kimliği. Uygulama türü: Masaüstü uygulaması. "
             "Oluşunca “JSON'u indir” de.", "url": _C + "apis/credentials"},
    {"id": "json", "title": "İndirdiğin JSON dosyasını seç",
     "text": "Aşağıdaki “JSON seç” düğmesiyle client_secret…json dosyasını göster; Jarvis kontrol edip yerine koyar."},
    {"id": "baglan", "title": "Bağlan",
     "text": "“Bağlan” düğmesine bas; tarayıcıda Google izin ekranı açılır. Salt okuma izni verirsin."},
]


def steps() -> list[dict]:
    return [dict(s) for s in _STEPS]


def step_url(step_id: str) -> str:
    """Yalnız tarayıcıda açılabilir adımların sabit adresi; başka her kimlik reddedilir."""
    for s in _STEPS:
        if s["id"] == step_id and s.get("url"):
            return s["url"]
    raise ValueError("Bilinmeyen adım.")


def client_problem(data) -> str | None:
    """İndirilen istemci dosyasının kullanılamaz olma nedeni, uygunsa None."""
    if not isinstance(data, dict) or not {"installed", "web"} & set(data):
        return "Bu bir Google OAuth istemci dosyası gibi görünmüyor (client_secret…json)."
    if "installed" not in data:
        return ("Bu istemci “Web uygulaması” türünde; Jarvis için “Masaüstü uygulaması” türünde yeni bir OAuth istemci "
                "kimliği oluşturup onun JSON'unu indir.")
    inner = data["installed"]
    if not isinstance(inner, dict) or not str(inner.get("client_id") or "").strip():
        return "Dosyada client_id yok; JSON'u Google Cloud'dan yeniden indir."
    if not str(inner.get("client_secret") or "").strip():
        return "Dosyada client_secret yok; JSON'u Google Cloud'dan yeniden indir."
    return None


def _packages_ok() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("googleapiclient", "google_auth_oauthlib"))


def status(api, production: bool) -> dict:
    """Doğrulanabilenlerin durumu ve sıradaki adım. `api`: google_api modülü (CRED, connected)."""
    cred, msg = "yok", "JSON dosyası henüz seçilmedi."
    try:
        raw = api.CRED.read_text(encoding="utf-8")
    except FileNotFoundError:
        raw = None
    except OSError:
        raw, cred, msg = None, "bozuk", "Kimlik dosyası okunamadı; JSON'u yeniden seç."
    if raw is not None:
        try:
            problem = client_problem(json.loads(raw))
        except ValueError:
            cred, msg = "bozuk", "Kimlik dosyası okunamadı; JSON'u yeniden seç."
        else:
            cred, msg = ("hazir", "Kimlik dosyası uygun.") if problem is None else ("sorunlu", problem)
    try:
        token = bool(api.connected())
    except PermissionError:
        token = False
    packages = _packages_ok()
    if cred != "hazir" and not token:
        nxt = "json"
    elif not packages and not token:
        nxt = "paketler"
    elif not token:
        nxt = "baglan"
    else:
        nxt = "bitti"
    return {"cred": cred, "cred_msg": msg, "packages": packages, "token": token, "production": bool(production),
            "next": nxt}
