"""Onaylı araç kayıtları veridir; Python modülü veya kurulum kodu üretilmez."""
from pathlib import Path
import re
import threading

from config import DATA_DIR
from modules import capability_hub, llm, permission_audit, permission_gate, permission_policy, service_store
from modules.diagnostics import record_failure as _diagnostic_failure
from modules.publish_services import _read_private_json, _write_private_json

ROOT = DATA_DIR / 'tool_wizard'
_LOCK = threading.RLock()
_PARAM_TYPES = {'string': 'str', 'integer': 'int', 'number': 'float', 'boolean': 'bool'}


def _record_failure(context):
    try:
        raise RuntimeError('Kullanıcı araç kaydı veya işlemi doğrulanamadı.') from None
    except RuntimeError:
        _diagnostic_failure(context)


def _path(owner):
    service_store.identity(owner)
    if not isinstance(owner, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', owner):
        raise ValueError('Geçersiz kullanıcı.')
    path = ROOT / (owner + '.json')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
        raise ValueError('Araç kayıt yolu sembolik bağ olamaz.')
    return path


def _validate(record):
    if (not isinstance(record, dict) or record.get('kind') != 'api' or record.get('class') != 'read'
            or not isinstance(record.get('candidate'), str) or not re.fullmatch('[a-f0-9]{16}', record['candidate'])
            or record.get('id') != 'custom_' + record['candidate']
            or not isinstance(record.get('name'), str) or not 1 <= len(record['name']) <= 120
            or not isinstance(record.get('params'), dict) or len(record['params']) > 12
            or any(not isinstance(k, str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,40}', k)
                   or v not in _PARAM_TYPES.values() for k, v in record['params'].items())):
        raise ValueError('Araç kaydı geçersiz.')
    return record


def _load(owner):
    path = _path(owner)
    if not path.exists():
        return {}
    records = _read_private_json(path, migrate=False)
    if len(records) > 100:
        raise ValueError('Araç kayıt sınırı aşıldı.')
    for ident, record in records.items():
        if _validate(record)['id'] != ident:
            raise ValueError('Araç kayıt kimliği eşleşmiyor.')
    return records


def _save(owner, record):
    _validate(record)
    with _LOCK:
        records = _load(owner)
        records[record['id']] = record
        if len(records) > 100:
            raise ValueError('En fazla 100 özel araç eklenebilir.')
        _write_private_json(_path(owner), records)


def discover(owner, query):
    service_store.identity(owner)
    return capability_hub.discover(owner, query)


def add_api(owner, candidate, endpoint, parameters, *, confirmed=False):
    service_store.identity(owner)
    if not isinstance(confirmed, bool):
        raise ValueError('Açık kullanıcı onayı gerekli.')
    result = capability_hub.public_binding(owner, candidate, endpoint, parameters, confirmed=confirmed)
    if not confirmed:
        return result
    row = next(row for row in capability_hub.rows(owner) if row['id'] == candidate)
    record = {'id': 'custom_' + candidate, 'kind': 'api', 'candidate': candidate,
              'name': row['name'], 'class': 'read',
              'params': {key: _PARAM_TYPES[value] for key, value in parameters.items()}}
    _save(owner, record)
    return {'state': 'done', 'id': record['id'], 'detail': 'Onaylı genel okuma aracı kaydedildi; canlı servis sınanmadı.'}


def _decision(owner, ident, action_class):
    service_store.identity(owner)
    result = permission_gate.decide({'class': action_class, 'target': ident, 'via': 'system'})
    decision, reason = permission_policy.apply(owner, ident, action_class, result['decision'], result['reason'])
    if decision not in ('allow', 'ask', 'deny'):
        raise ValueError('Geçersiz izin kararı.')
    permission_audit.record(owner, decision, action_class, ident, 'system', reason)
    return decision


def execute(owner, ident, parameters, *, approve=False):
    try:
        if not isinstance(approve, bool):
            raise ValueError('Geçersiz onay.')
        record = _load(owner)[ident]
        decision = _decision(owner, ident, record['class'])
        if decision == 'deny':
            return {'state': 'blocked', 'detail': 'Politika: Engelle.'}
        if decision == 'ask' and not approve:
            return {'state': 'approval', 'detail': 'Bu eylem için somut onay gerekli.'}
        data = capability_hub.read(owner, record['candidate'], parameters)
        return {'state': 'done', 'data': data}
    except Exception:
        _record_failure('modules/tool_wizard.py:execute')
        return {'state': 'blocked', 'detail': 'Araç işlemi doğrulanamadı; otomatik tekrar yapılmadı.'}


def _status(owner, ident):
    try:
        _load(owner)[ident]
        return {'state': 'ready', 'detail': 'Kullanıcı onaylı araç kaydı var; canlı servis sınanmadı.'}
    except Exception:
        _record_failure('modules/tool_wizard.py:status')
        return {'state': 'error', 'detail': 'Bu kullanıcı için araç kaydı doğrulanamadı.'}


def _cancel(owner):
    try:
        service_store.identity(owner)
        return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}
    except Exception:
        _record_failure('modules/tool_wizard.py:cancel')
        return {'cancelled': False, 'detail': 'Araç kullanıcısı doğrulanamadı.'}


def contracts(owner):
    result = {}
    for ident, record in _load(owner).items():
        result[ident] = {'id': ident, 'name': record['name'], 'area': 'cihaz', 'icon': 'globe',
                         'actions': [{'id': 'invoke', 'name': 'Veriyi oku', 'desc': 'Onaylı sabit genel GET bağlantısı.',
                                      'class': record['class'], 'params': record['params']}],
                         'status': lambda ident=ident: _status(owner, ident),
                         'cancel': lambda: _cancel(owner)}
    return result
