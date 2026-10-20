"""Mevcut Hoca girişlerinin sözleşmesi; ders/ilerleme veya model davranışını değiştirmez."""
from modules.diagnostics import record_failure as _record_failure


def status():
    try:
        from modules import hoca
        if not callable(hoca.handle) or not callable(hoca.snapshot):
            raise ValueError('Hoca girişi bulunamadı.')
        return {'state': 'ready', 'detail': 'Hoca girişleri mevcut; ders veya model çağrısı başlatılmadı.'}
    except Exception:
        _record_failure('modules/tool_hoca.py:status')
        return {'state': 'error', 'detail': 'Hoca aracı bulunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu sözleşme ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'hoca', 'name': 'Hoca', 'area': 'egitim', 'icon': 'book',
    'actions': [
        {'id': 'handle', 'name': 'Ders komutu', 'desc': 'Mevcut Hoca komut girişi; profil aktif kullanıcıdan gelir.',
         'class': 'local_reversible', 'params': {'text': 'str', 'enabled': 'bool'}},
        {'id': 'snapshot', 'name': 'Ders görünümü', 'desc': 'Mevcut Hoca profil görünümü; yeni model çağrısı yoktur.',
         'class': 'read', 'params': {'enabled': 'bool', 'now': 'float'}},
    ],
    'status': status, 'cancel': cancel,
}
