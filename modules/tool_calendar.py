"""Mevcut Google Takvim okuma girişlerinin sözleşmesi; takvim davranışı değişmez."""
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
        _record_failure('modules/tool_calendar.py:status')
        return {'state': 'error', 'detail': 'Bağlantı durumu okunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'calendar', 'name': 'Takvim', 'area': 'iletisim', 'icon': 'calendar',
    'actions': [
        {'id': 'agenda', 'name': 'Ajanda', 'desc': 'Mevcut Google Takvim ajandası.', 'class': 'read', 'params': {'day_offset': 'int', 'label': 'str'}},
        {'id': 'day_events', 'name': 'Günün etkinlikleri', 'desc': 'Mevcut günlük Google Takvim okuması.', 'class': 'read', 'params': {'day_offset': 'int'}},
        {'id': 'range_events', 'name': 'Tarih aralığı', 'desc': 'Mevcut tarih aralığı etkinlik okuması.', 'class': 'read', 'params': {'start_offset': 'int', 'days': 'int'}},
    ],
    'status': status, 'cancel': cancel,
}
