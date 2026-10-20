"""Mevcut fiyat/kur yanıtlarının sözleşmesi; alım/satım veya hesap işlemi açmaz."""
from modules.diagnostics import record_failure as _record_failure


def status():
    try:
        from modules import finance
        if not callable(finance.answer):
            raise ValueError('Finans girişi bulunamadı.')
        return {'state': 'ready', 'detail': 'Fiyat/kur girişi mevcut; canlı veri sınanmadı.'}
    except Exception:
        _record_failure('modules/tool_finance.py:status')
        return {'state': 'error', 'detail': 'Finans aracı bulunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'finance', 'name': 'Finans', 'area': 'finans', 'icon': 'chart',
    'actions': [{'id': 'answer', 'name': 'Fiyat ve kur',
                 'desc': 'Mevcut finance.answer fiyat/kur okuması; yatırım veya ödeme işlemi değildir.',
                 'class': 'read', 'params': {'text': 'str'}}],
    'status': status, 'cancel': cancel,
}
