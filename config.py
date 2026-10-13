"""Jarvis yapılandırması (Gemini altyapısı)."""
import json
import os
import threading
import tempfile
from pathlib import Path

DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR") or (Path.home() / ".jarvis"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"      # arayüzdeki Ayarlar sayfası buraya yazar; buradakiler aşağıdaki varsayılanların yerine geçer


_cache: dict = {"key": None, "text": "{}"}


def load_settings() -> dict:
    """Ayarları okur. Dosya değişmediyse diskten tekrar okunmaz (her yapay zeka çağrısında okunuyordu)."""
    try:
        st = SETTINGS_FILE.stat()
        key = (st.st_mtime_ns, st.st_size)
        if key != _cache["key"]:
            _cache["text"], _cache["key"] = SETTINGS_FILE.read_text(encoding="utf-8"), key
        data = json.loads(_cache["text"])     # her seferinde yeni kopya: çağıran değiştirse de önbellek bozulmaz
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


_save_lock = threading.RLock()


def save_settings(**changes) -> None:
    """Ayarları birleştirip kaydeder (None verilen anahtar silinir). Aynı anda iki kayıt gelirse biri kaybolmasın diye sırayla."""
    with _save_lock:
        data = load_settings()
        for k, v in changes.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        fd, temporary = tempfile.mkstemp(prefix='.jarvis-settings-', suffix='.json', dir=SETTINGS_FILE.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, SETTINGS_FILE)
        finally:
            Path(temporary).unlink(missing_ok=True)
        _cache["key"] = None


_S = load_settings()


def _tuple(value, default) -> tuple:
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    return tuple(v for v in (value or ()) if v) or default


MODEL = _S.get("model") or os.getenv("JARVIS_MODEL", "gemini-3.5-flash-lite")   # model kodu AI Studio'daki ile aynı olmalı
# Ana model kota/yoğunluk/404 hatası verirse sırayla denenecek yedekler (adları models sayfasından doğrula)
FALLBACK_MODELS = _tuple(_S.get("fallback_models"), ("gemini-3.5-flash",))
PROFILE_DB = DATA_DIR / "profile.json"          # eski tek kullanıcılı profil (otomatik taşınır)
USERS_DIR = DATA_DIR / "users"                  # her kullanıcının ayrı profili
USERS_DIR.mkdir(exist_ok=True)
ACTIVE_FILE = DATA_DIR / "active_user.txt"      # son konuşan kullanıcı
DEFAULT_USER = "Hamdi"                          # ilk açılışta kullanılacak kullanıcı
KEY_FILE = DATA_DIR / "gemini_key.txt"
GROQ_KEY_FILE = DATA_DIR / "groq_key.txt"
WAKE_WORD = _S.get("wake_word") or "Jarvis"          # Ayarlar sayfasından değiştirilebilir
ASSISTANT_NAME = (_S.get("assistant_name") or "Jarvis").strip() or "Jarvis"   # asistanın adı (ekranda ve konuşurken)
WAKE_ALIASES = _tuple(_S.get("wake_aliases"), (("jarvis", "hey jarvis", "yarvis") if WAKE_WORD.casefold() == "jarvis" else ("şiri", "seri") if WAKE_WORD.casefold() == "siri" else (WAKE_WORD.casefold(),)))
ANNOUNCE_UNKNOWN = bool(_S.get("announce_unknown", True))       # anlaşılmazsa "Anlamadım" de; sessiz kalsın istersen False
SESSION_SECONDS = int(_S.get("session_seconds") or 30)          # uyandırdıktan sonra kaç saniye uyandırma adı istemesin
INPUT_DEVICE = (lambda v: int(v) if str(v).strip().isdigit() else (str(v).strip() or None))(_S.get("input_device") or "")           # mikrofon: None = Windows varsayılanı; örn. "Senary" ya da cihaz numarası
CAMERA_INDEX = int(_S.get("camera_index") or 0)              # birden fazla kameran varsa 1, 2 dene
LANGUAGE = "tr-TR"

def _privacy():
    from modules import privacy   # geç içe aktarım: privacy de config'i kullanır
    return privacy


def _protect_youtube_key(key: str) -> str:
    stored = _privacy().protect(key)
    if not stored.startswith('dpapi:'):
        raise OSError('YouTube anahtarı Windows korumasıyla saklanamadı; anahtar kaydedilmedi.')
    return stored


def set_youtube_key(key: str) -> None:
    """Use Windows account protection; never fall back to plaintext/base64."""
    key = str(key or '').strip()
    stored = _protect_youtube_key(key) if key else None
    save_settings(youtube_key=None, youtube_key_protected=stored)


def get_youtube_key() -> str:
    """Migrate legacy plaintext atomically, then prefer an environment key."""
    with _save_lock:
        settings = load_settings()
        stored = settings.get('youtube_key_protected') or ''
        legacy = str(settings.get('youtube_key') or '').strip()
        if legacy:
            stored = _protect_youtube_key(legacy)
            save_settings(youtube_key=None, youtube_key_protected=stored)
            _S.pop('youtube_key', None)
        environment = os.getenv('YOUTUBE_API_KEY', '').strip()
        if environment:
            return environment
        if not stored:
            return ''
        if not str(stored).startswith('dpapi:'):
            raise ValueError('YouTube anahtarının korumalı kayıt biçimi geçersiz; yeniden ekle.')
        key = _privacy().unprotect(stored)
        if not key:
            raise ValueError('YouTube anahtarı bu Windows hesabında çözülemedi; yeniden ekle.')
        return key


def save_api_key(key: str) -> None:
    """Anahtarı korumalı yazar (Windows'ta yalnız bu kullanıcı hesabı çözebilir)."""
    global API_KEY
    KEY_FILE.write_text(_privacy().protect(key.strip()), encoding="utf-8")
    API_KEY = key.strip()


def get_api_key() -> str:
    """Yalnız legacy/bakım Gemini anahtarını döndürür; kullanıcıdan interaktif anahtar istemez.

    Normal JARVIS oturumları modules.llm içindeki kullanıcıya özel anahtar deposunu kullanır.
    Bu fonksiyon eski kurulum uyumluluğu içindir ve hiçbir kullanıcıya fallback sağlamaz.
    """
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        try:
            raw = KEY_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ''
        except (OSError, UnicodeError):
            from modules.diagnostics import record_failure
            record_failure('config.py:legacy_key_read')
            return ''
        key = _privacy().unprotect(raw)
        if key and not raw.startswith(("dpapi:", "b64:")):
            try:
                save_api_key(key)
            except OSError:
                from modules.diagnostics import record_failure
                record_failure('config.py:legacy_key_migration')
    return (key or "").strip()


def legacy_key_protected() -> bool:
    """Legacy key status must never make the settings screen fail."""
    try:
        return KEY_FILE.read_text(encoding='utf-8').startswith('dpapi:')
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError):
        from modules.diagnostics import record_failure
        record_failure('config.py:legacy_key_status')
        return False

API_KEY = get_api_key()



def save_groq_key(key: str) -> None:
    """Groq API anahtarını korumalı yazar."""
    GROQ_KEY_FILE.write_text(_privacy().protect(key.strip()), encoding="utf-8")


def get_groq_key() -> str:
    """Sıra: GROQ_API_KEY ortam değişkeni -> kayıtlı dosya. Yoksa boş."""
    key = os.getenv("GROQ_API_KEY")
    if not key and GROQ_KEY_FILE.exists():
        key = _privacy().unprotect(GROQ_KEY_FILE.read_text(encoding="utf-8"))
    return (key or "").strip()
