"""Kullanıcı hedefinin gerçekten tamamlandığını tanımlayan ortak sonuç sözleşmeleri.

Ajan türleri kendi çıktı biçimini korur; bu modül başarı kimliğini ve alanlar arası ortak
kuralları tek yerde tutar. Eski kalıcı sonuçlar metadata olmadan da okunabilir; yeni
sonuçlar contract kimliği taşır.
"""
from __future__ import annotations
import re

VERSION = 1

_TASK_IDS = {
    'research': 'OUTCOME-RESEARCH-VERIFIED',
    'writer': 'OUTCOME-ARTIFACT-WRITTEN',
    'coder': 'OUTCOME-CODE-TESTED',
    'browser': 'OUTCOME-BROWSER-VERIFIED',
    'verify': 'OUTCOME-DEPENDENCIES-VERIFIED',
    'account': 'OUTCOME-ACCOUNT-READ-VERIFIED',
    'publish': 'OUTCOME-REMOTE-ACCEPTED',
    'media': 'OUTCOME-MEDIA-VERIFIED',
}

_LOCAL_IDS = {
    'action': 'OUTCOME-JARVIS-ACTION',
    'desktop': 'OUTCOME-PC-DESKTOP-VERIFIED',
    'document': 'OUTCOME-DOCUMENT-VERIFIED',
    'observe': 'OUTCOME-OBSERVATION-VERIFIED',
    'application': 'OUTCOME-APPLICATION-OPENED',
    'diagnose': 'OUTCOME-DIAGNOSIS-COMPLETED',
    'sharing': 'OUTCOME-SHARING-STATE-VERIFIED',
    'schedule': 'OUTCOME-SCHEDULE-PERSISTED',
    'system': 'OUTCOME-PC-SYSTEM-VERIFIED',
    'data': 'OUTCOME-DATA-VERIFIED',
    'capability': 'OUTCOME-CAPABILITY-VERIFIED',
    'monitor': 'OUTCOME-MONITOR-VERIFIED',
}


def _fold(text: str) -> str:
    return ' '.join(str(text or '').casefold().replace('ı', 'i').split()).strip(' .!?')


def open_only_request(text: str) -> bool:
    """True only when opening the application is itself the complete user outcome."""
    low = _fold(text)
    if re.search(r'\b(?:ve|sonra|ardindan|ardından|sonrasinda|sonrasında|acip|açıp|actiktan|açtıktan)\b', low):
        return False
    action_verbs = re.findall(
        r'\b(?:ac|aç|baslat|başlat|calistir|çalıştır|kapat|degistir|değiştir|ayarla|yaz|gir|sec|seç|tikla|tıkla|uygula|kaydet|sil|gonder|gönder)\w*',
        low,
    )
    if len(action_verbs) != 1 or not re.match(r'^(?:ac|aç|baslat|başlat|calistir|çalıştır)', action_verbs[0]):
        return False
    return bool(re.fullmatch(
        r'(?:lutfen\s+|lütfen\s+)?(?:ac|aç|baslat|başlat|calistir|çalıştır)\s+.+|'
        r'(?:lutfen\s+|lütfen\s+)?.+?\s+(?:uygulamasini\s+|uygulamasını\s+)?'
        r'(?:ac|aç|baslat|başlat|calistir|çalıştır)(?:ar misin|ar mısın|ir misin|ır mısın)?',
        low,
    ))


def contract_id(kind: str, output: dict | None = None, *, local: bool = False) -> str:
    table = _LOCAL_IDS if local else _TASK_IDS
    if kind not in table:
        prefix = 'OUTCOME-LOCAL' if local else 'OUTCOME-TASK'
        return prefix + '-' + re.sub(r'[^A-Z0-9]+', '-', str(kind).upper()).strip('-')
    if kind == 'research' and isinstance(output, dict) and output.get('news_article'):
        return 'OUTCOME-RESEARCH-NEWS-VERIFIED'
    return table[kind]


def attach(kind: str, output: dict, *, local: bool = False) -> dict:
    """Attach immutable contract metadata to a newly completed result."""
    result = dict(output)
    result['outcome_contract'] = {
        'version': VERSION,
        'id': contract_id(kind, result, local=local),
        'kind': kind,
        'scope': 'local' if local else 'task',
    }
    return result


def validate_metadata(kind: str, output: dict, *, local: bool = False, legacy_ok: bool = True) -> bool:
    """Validate contract metadata when present; optionally tolerate pre-contract persisted results."""
    meta = output.get('outcome_contract') if isinstance(output, dict) else None
    if meta is None and legacy_ok:
        return True
    if not isinstance(meta, dict):
        raise ValueError('Sonuç sözleşmesi kaydı geçersiz.')
    if meta.get('version') != VERSION or meta.get('kind') != kind:
        raise ValueError('Sonuç sözleşmesi sürümü veya türü eşleşmiyor.')
    if meta.get('scope') != ('local' if local else 'task'):
        raise ValueError('Sonuç sözleşmesi kapsamı eşleşmiyor.')
    if meta.get('id') != contract_id(kind, output, local=local):
        raise ValueError('Sonuç sözleşmesi kimliği çıktı kanıtıyla eşleşmiyor.')
    return True


def validate_common(kind: str, output: dict, *, local: bool = False) -> bool:
    """Cross-cutting success rules shared by every adapter."""
    if not isinstance(output, dict) or output.get('state') != 'done':
        raise ValueError('Kullanıcı sonucu tamamlanmış değil.')
    text = output.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Tamamlanan kullanıcı sonucunun teslim metni boş.')
    if local and output.get('local_evidence') != kind:
        raise ValueError('Yerel sonuç türü kanıtla eşleşmiyor.')
    validate_metadata(kind, output, local=local)
    return True
