"""Mevcut Gmail okuma girişlerinin keşfedilebilir sözleşmesi; yeni işlem yolu açmaz."""
from modules.diagnostics import record_failure as _record_failure


def status():
    try:
        from modules import google_api, llm, service_store
        from modules.publish_services import _credential_path
        owner = llm._key_context.get()
        if not owner:
            return {'state': 'not_connected', 'detail': 'Kullanıcı seçilmedi.'}
        service_store.identity(owner)
        path = _credential_path(google_api.DATA_DIR / 'google_users' / owner / google_api.TOKEN.name)
        if path.is_file():
            return {'state': 'ready', 'detail': 'Yerel bağlantı kaydı var; canlı hesap sınanmadı.'}
        return {'state': 'not_connected', 'detail': 'Bu kullanıcı için yerel bağlantı kaydı yok.'}
    except Exception:
        _record_failure('modules/tool_mail.py:status')
        return {'state': 'error', 'detail': 'Bağlantı durumu okunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'mail', 'name': 'Mail', 'area': 'iletisim', 'icon': 'mail',
    'actions': [
        {'id': 'unread_mail', 'name': 'Okunmamış mail', 'desc': 'Mevcut Gmail okunmamış mail girişi.', 'class': 'read', 'params': {'limit': 'int'}},
        {'id': 'important_text', 'name': 'Önemli mail', 'desc': 'Mevcut Gmail önemli mail görünümü.', 'class': 'read', 'params': {}},
        {'id': 'awaiting_text', 'name': 'Cevap takibi', 'desc': 'Mevcut Gmail cevap bekleyen mail görünümü.', 'class': 'read', 'params': {'kind': 'str'}},
    ],
    'status': status, 'cancel': cancel,
}
