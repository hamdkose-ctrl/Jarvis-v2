"""Saf eylem sınıflandırması; izin vermez ve hiçbir yürütme yoluna bağlı değildir.

Yalnız açıkça tanınan okuma adları read olur. Bilinmeyen yol/ad/tip ve
belirsiz birleşik adlar system_config döndürür; riskli sözcük önceliklidir.
"""
import re
from modules import turkish_text

_VIAS = {'outbox', 'desktop', 'browser', 'file', 'system'}
_MONEY = ('ode', 'pay', 'satin al', 'buy', 'purchase', 'sifre', 'password', 'credential', 'pin')
_SYSTEM = ('ayarlar', 'settings', 'kayit defteri', 'registry', 'system configuration')
_DESTROY = ('sil', 'delete', 'remove', 'bicimlendir', 'format', 'uzerine yaz', 'overwrite', 'erase')
_PUBLISH = ('yayinla', 'publish', 'post', 'paylas', 'share')
_SEND = ('gonder', 'send', 'submit', 'mesaj gonder', 'send message')
_READ = {'ac', 'open', 'oku', 'read', 'goster', 'show', 'view', 'goruntule', 'listele', 'list'}
_REVERSIBLE = {'kopyala', 'copy', 'yeni klasor', 'create folder', 'new folder'}


def _normal(value):
    return ' '.join(turkish_text.fold(value).casefold().replace('\u0307', '').split())


def _has(text, phrases):
    return any(re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text) for phrase in phrases)


def classify(via: str, name: str, target: str = '') -> str:
    """Yol ve etiketi sınıflandırır; tanınmayan eylem ASLA salt okuma sayılmaz."""
    return classify_detail(via, name, target)[0]


def classify_detail(via: str, name: str, target: str = '') -> tuple[str, bool]:
    """(sınıf, tanındı). Tanınmadı = hiçbir kurala uymadı; sınıf yine system_config'tir.

    Çağıran yol, tanınmayan adı kendi mevcut politikasına bırakabilir (ör. masaüstünde
    Hesap Makinesi rakam düğmeleri); geçersiz girdi de tanınmadı sayılır."""
    if (not isinstance(via, str) or not isinstance(name, str) or not isinstance(target, str)
            or len(via) > 32 or len(name) > 512 or len(target) > 2048):
        return 'system_config', False
    via, name, target = _normal(via), _normal(name), _normal(target)
    if via not in _VIAS or not name:
        return 'system_config', False
    # Açık para/kimlik ve sistem hedefleri genel bir "Aç" etiketinden önce gelir.
    if _has(name, _MONEY) or _has(target, _MONEY):
        return 'money_credential', True
    if _has(name, _SYSTEM) or _has(target, _SYSTEM):
        return 'system_config', True
    if _has(name, _DESTROY):
        return 'local_destructive', True
    if _has(name, _PUBLISH):
        return 'publish', True
    if _has(name, _SEND):
        return 'message_out', True
    if name in _READ:
        return 'read', True
    if via in {'file', 'desktop'} and name in _REVERSIBLE:
        return 'local_reversible', True
    return 'system_config', False
