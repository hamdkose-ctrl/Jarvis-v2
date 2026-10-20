"""Tek dosya işlemlerinin sözleşmesi; gerçek yol/sahiplik denetimi file_ops'ta kalır."""
from modules.diagnostics import record_failure as _record_failure


def status():
    try:
        from modules import file_ops
        if not callable(file_ops.handle) or not callable(file_ops.undo):
            raise ValueError('Dosya girişi bulunamadı.')
        return {'state': 'ready', 'detail': 'Yerel dosya işlem girişleri mevcut; işlem başlatılmadı.'}
    except Exception:
        _record_failure('modules/tool_files.py:status')
        return {'state': 'error', 'detail': 'Dosya aracı bulunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu sözleşme ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'file', 'name': 'Dosya', 'area': 'cihaz', 'icon': 'folder',
    'actions': [
        {'id': 'handle', 'name': 'Dosya işlemi', 'desc': 'Mevcut taşıma, adlandırma ve metin oluşturma girişi.',
         'class': 'local_reversible', 'params': {'command': 'str'}},
        {'id': 'undo', 'name': 'Geri al', 'desc': 'Mevcut kullanıcıya özel, değişmiş dosyayı koruyan geri alma.',
         'class': 'local_reversible', 'params': {}},
    ],
    'status': status, 'cancel': cancel,
}
