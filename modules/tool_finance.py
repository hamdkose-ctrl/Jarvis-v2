"""Mevcut fiyat/kur yanıtlarının sözleşmesi; alım/satım veya hesap işlemi açmaz."""
import json

from modules.diagnostics import record_failure as _record_failure


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Finans isteğinde yinelenen JSON alanı var.')
        result[key] = value
    return result


def read(arguments_json):
    """Run a typed finance request from the exact JSON protocol after Core validation."""
    if not isinstance(arguments_json, str) or len(arguments_json) > 6000:
        raise ValueError('Finans isteği sınırlı JSON metni olmalı.')
    try:
        arguments = json.loads(arguments_json, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as exc:
        raise ValueError('Finans isteği geçerli JSON olmalı.') from exc
    if not isinstance(arguments, dict):
        raise ValueError('Finans isteği JSON nesnesi olmalı.')

    from modules import brain_core_map, finance
    plan = brain_core_map.core_plan('finance.read', arguments)
    if plan is None or plan[0] != 'finance_read':
        raise ValueError('Finans isteğinin tipli alanları doğrulanamadı.')
    request = finance.request_from_slots(plan[1])
    return finance.answer_request(request)


def status():
    try:
        from modules import finance
        if not callable(finance.request_from_slots) or not callable(finance.answer_request):
            raise ValueError('Finans girişi bulunamadı.')
        return {'state': 'ready', 'detail': 'Fiyat/kur girişi mevcut; canlı veri sınanmadı.'}
    except Exception:
        _record_failure('modules/tool_finance.py:status')
        return {'state': 'error', 'detail': 'Finans aracı bulunamadı.'}


def cancel():
    return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}


CONTRACT = {
    'id': 'finance', 'name': 'Finans', 'area': 'finans', 'icon': 'chart',
    'actions': [{'id': 'read', 'name': 'Fiyat ve kur',
                 'desc': 'Core tarafından doğrulanmış finance.read alanları içeren JSON; yatırım veya ödeme işlemi değildir.',
                 'class': 'read', 'params': {'arguments_json': 'str'}}],
    'status': status, 'cancel': cancel,
}
