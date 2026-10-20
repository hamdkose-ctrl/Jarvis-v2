"""Onaylı araç kayıtları veridir; Python modülü veya kurulum kodu üretilmez."""
from pathlib import Path
import json
import ipaddress
import os
import re
import subprocess
import tempfile
import threading
import uuid
from urllib.parse import urlsplit, urlunsplit

from config import DATA_DIR
from modules import capability_hub, llm, permission_audit, permission_gate, permission_policy, service_store
from modules.diagnostics import record_failure as _diagnostic_failure
from modules.publish_services import _read_private_json, _write_private_json

ROOT = DATA_DIR / 'tool_wizard'
_LOCK = threading.RLock()
_RUNNING = {}
_DEVICE_BUSY = set()
_PARAM_TYPES = {'string': 'str', 'integer': 'int', 'number': 'float', 'boolean': 'bool'}
_PROGRAM_CLASSES = permission_gate.CLASSES - {'money_credential', 'system_config'}


def _argument_schema(arguments):
    if not isinstance(arguments, list) or len(arguments) > 40:
        raise ValueError('Argüman şablonu en fazla 40 öğeli liste olmalı.')
    fields = set()
    for argument in arguments:
        if not isinstance(argument, str) or len(argument) > 4000 or '\x00' in argument:
            raise ValueError('Geçersiz argüman şablonu.')
        found = re.findall(r'\{([a-zA-Z][a-zA-Z0-9_]{0,40})\}', argument)
        remaining = re.sub(r'\{([a-zA-Z][a-zA-Z0-9_]{0,40})\}', '', argument)
        if '{' in remaining or '}' in remaining:
            raise ValueError('Yalnız {alan} biçiminde düz parametre kullanılabilir.')
        fields.update(found)
    if len(fields) > 12:
        raise ValueError('En fazla 12 parametre kullanılabilir.')
    return {field: 'str' for field in sorted(fields)}


def _program(path):
    if not isinstance(path, str) or len(path) > 2000 or '\x00' in path or not Path(path).is_absolute():
        raise ValueError('Programın açık tam yolu gerekli.')
    executable = Path(path)
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (executable, *executable.parents)):
        raise ValueError('Program yolu sembolik bağ olamaz.')
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('Seçilen program kurulu değil veya yürütülemiyor.')
    if os.name == 'nt' and executable.suffix.lower() != '.exe':
        raise ValueError('Windows programı .exe olmalı; BAT/CMD kabuk dosyaları kabul edilmez.')
    return str(executable)


def _device(address, key, allow_private):
    if (not isinstance(address, str) or len(address) > 1000 or any(c.isspace() or ord(c) < 32 for c in address)
            or not isinstance(allow_private, bool)):
        raise ValueError('Geçersiz cihaz adresi veya özel ağ onayı.')
    url = urlsplit(address)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment or '%' in url.hostname):
        raise ValueError('Cihaz adresinde kimlik bilgisi, sorgu veya parça kullanılamaz.')
    host = '127.0.0.1' if url.hostname == 'localhost' else url.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError('Cihaz için açık IP veya localhost gerekli; DNS adları kabul edilmez.') from None
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast or (ip.is_reserved and not ip.is_loopback):
        raise ValueError('Link-local/metadata, belirsiz, çoklu yayın veya ayrılmış cihaz adresi kullanılamaz.')
    if not ip.is_global and (not allow_private or not (ip.is_private or ip.is_loopback)):
        raise ValueError('Özel IP/localhost için ayrıca açık özel ağ onayı gerekli.')
    if ip.is_global and url.scheme != 'https':
        raise ValueError('Genel IP cihazı HTTPS gerektirir.')
    if not isinstance(key, str) or not 1 <= len(key) <= 1024 or any(ord(c) < 32 or ord(c) > 126 for c in key):
        raise ValueError('Geçersiz cihaz anahtarı.')
    port = url.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Geçersiz cihaz portu.')
    netloc = ('[' + str(ip) + ']') if ip.version == 6 else str(ip)
    if port is not None:
        netloc += ':' + str(port)
    return urlunsplit((url.scheme, netloc, url.path or '/', '', ''))


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
    if (not isinstance(record, dict) or record.get('kind') not in ('api', 'program', 'device')
            or not isinstance(record.get('id'), str) or not re.fullmatch('custom_[a-f0-9]{16}', record['id'])
            or not isinstance(record.get('name'), str) or not 1 <= len(record['name']) <= 120
            or not isinstance(record.get('params'), dict) or len(record['params']) > 12
            or any(not isinstance(k, str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,40}', k)
                   or v not in _PARAM_TYPES.values() for k, v in record['params'].items())):
        raise ValueError('Araç kaydı geçersiz.')
    if record['kind'] == 'api':
        if (record.get('class') != 'read' or not isinstance(record.get('candidate'), str)
                or not re.fullmatch('[a-f0-9]{16}', record['candidate']) or record['id'] != 'custom_' + record['candidate']):
            raise ValueError('API yalnız read sınıfında olabilir.')
    elif record['kind'] == 'program':
        if (not isinstance(record.get('class'), str) or record['class'] not in _PROGRAM_CLASSES
                or not isinstance(record.get('program'), str) or not Path(record['program']).is_absolute()
                or record['params'] != _argument_schema(record.get('arguments'))):
            raise ValueError('Yerel program kaydı geçersiz; para ve sistem sınıfları kilitli.')
    else:
        if record.get('class') != 'physical' or record['params'] != {'payload': 'str'}:
            raise ValueError('Cihaz komutları yalnız physical sınıfında olabilir.')
        if _device(record.get('address'), record.get('key'), record.get('allow_private')) != record['address']:
            raise ValueError('Cihaz adresi kesin kayıtla eşleşmiyor.')
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


def add_program(owner, name, program, arguments, *, action_class='local_destructive', confirmed=False):
    service_store.identity(owner)
    if not isinstance(confirmed, bool):
        raise ValueError('Açık kullanıcı onayı gerekli.')
    record = {'id': 'custom_' + uuid.uuid4().hex[:16], 'kind': 'program', 'name': name,
              'program': _program(program), 'arguments': arguments, 'params': _argument_schema(arguments), 'class': action_class}
    _validate(record)
    if not confirmed:
        return {'state': 'approval', 'text': name + '\n' + program + '\n' + json.dumps(arguments, ensure_ascii=False) + '\nSınıf: ' + action_class}
    _save(owner, record)
    return {'state': 'done', 'id': record['id'], 'detail': 'Kullanıcının seçtiği yerel program kaydedildi; henüz yürütülmedi.'}


def _run_program(owner, record, parameters):
    if (not isinstance(parameters, dict) or set(parameters) != set(record['params'])
            or any(not isinstance(v, str) or len(v) > 2000 or '\x00' in v for v in parameters.values())):
        raise ValueError('Program parametreleri şablonla eşleşmiyor.')
    try:
        program = _program(record['program'])
    except ValueError:
        return {'state': 'not_connected', 'detail': 'Program kurulu değil veya artık güvenle yürütülemiyor.'}
    argv = [program, *[re.sub(r'\{([a-zA-Z][a-zA-Z0-9_]{0,40})\}', lambda m: parameters[m[1]], argument)
                      for argument in record['arguments']]]
    key = (owner, record['id'])
    process = None
    try:
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            with _LOCK:
                if key in _RUNNING:
                    raise ValueError('Bu araç zaten çalışıyor.')
                process = subprocess.Popen(argv, shell=False, stdin=subprocess.DEVNULL, stdout=output, stderr=errors)
                _RUNNING[key] = process
            try:
                process.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
                return {'state': 'error', 'detail': 'Yerel program zaman aşımında durduruldu.'}
            if process.returncode != 0:
                return {'state': 'error', 'detail': 'Yerel program başarı kodu döndürmedi.'}
            output.seek(0)
            raw = output.read(20001)
            return {'state': 'done', 'data': {'text': raw[:20000].decode('utf-8', errors='replace'), 'truncated': len(raw) > 20000}}
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
            except Exception:
                _record_failure('modules/tool_wizard.py:program_cleanup')
            with _LOCK:
                if _RUNNING.get(key) is process:
                    _RUNNING.pop(key)


def add_device(owner, name, address, key, *, allow_private=False, confirmed=False):
    service_store.identity(owner)
    if not isinstance(confirmed, bool):
        raise ValueError('Açık kullanıcı onayı gerekli.')
    record = {'id': 'custom_' + uuid.uuid4().hex[:16], 'kind': 'device', 'name': name,
              'address': _device(address, key, allow_private), 'key': key,
              'allow_private': allow_private, 'class': 'physical', 'params': {'payload': 'str'}}
    _validate(record)
    if not confirmed:
        return {'state': 'approval', 'key': '***', 'text': name + '\n' + record['address'] + '\nAnahtar: ***\n'
                + ('Özel IP/localhost erişimini açıkça onaylıyorsunuz. ' if allow_private else '')
                + 'GET okuma; POST fiziksel komutu her seferinde ayrıca onay ister. Fiziksel durdurma protokolü tanımlı değil.'}
    _save(owner, record)
    return {'state': 'done', 'id': record['id'], 'address': '***', 'key': '***',
            'detail': 'Kullanıcı onaylı cihaz kaydı eklendi; gerçek cihaz sınanmadı.'}


def _device_request(owner, record, parameters, action):
    from modules.tool_printer import _http
    address = _device(record['address'], record['key'], record['allow_private'])
    if action == 'read':
        if parameters != {}:
            raise ValueError('Cihaz okuması ek parametre kabul etmez.')
        payload = None
    else:
        if (not isinstance(parameters, dict) or set(parameters) != {'payload'}
                or not isinstance(parameters['payload'], str) or len(parameters['payload']) > 20000):
            raise ValueError('Cihaz komutu sınırlı JSON nesnesi gerektirir.')
        payload = json.loads(parameters['payload'])
        if not isinstance(payload, dict):
            raise ValueError('Cihaz komutu JSON nesnesi olmalı.')
    key = (owner, record['id'])
    with _LOCK:
        if key in _DEVICE_BUSY:
            raise ValueError('Bu cihaz isteği zaten sürüyor.')
        _DEVICE_BUSY.add(key)
    try:
        data = _http({'address': address, 'key': record['key']}, 'GET' if action == 'read' else 'POST', '', payload)
        return {'state': 'done', 'data': data, 'detail': 'HTTP yanıtı kabul edildi; fiziksel sonuç doğrulanmadı.'}
    finally:
        with _LOCK:
            _DEVICE_BUSY.discard(key)


def execute(owner, ident, parameters, *, approve=False, action='invoke'):
    try:
        if not isinstance(approve, bool):
            raise ValueError('Geçersiz onay.')
        record = _load(owner)[ident]
        if action not in (('invoke', 'read') if record['kind'] == 'device' else ('invoke',)):
            raise ValueError('Geçersiz araç eylemi.')
        action_class = 'read' if record['kind'] == 'device' and action == 'read' else record['class']
        decision = _decision(owner, ident, action_class)
        if decision == 'deny':
            return {'state': 'blocked', 'detail': 'Politika: Engelle.'}
        if decision == 'ask' and not approve:
            return {'state': 'approval', 'detail': 'Bu eylem için somut onay gerekli.'}
        if action_class == 'physical' and not approve:
            return {'state': 'approval', 'detail': 'Fiziksel eylem her seferinde somut onay ister.'}
        if record['kind'] == 'program':
            return _run_program(owner, record, parameters)
        if record['kind'] == 'device':
            return _device_request(owner, record, parameters, action)
        data = capability_hub.read(owner, record['candidate'], parameters)
        return {'state': 'done', 'data': data}
    except Exception:
        _record_failure('modules/tool_wizard.py:execute')
        return {'state': 'blocked', 'detail': 'Araç işlemi doğrulanamadı; otomatik tekrar yapılmadı.'}


def _status(owner, ident):
    try:
        record = _load(owner)[ident]
        if record['kind'] == 'device':
            with _LOCK:
                if (owner, ident) in _DEVICE_BUSY:
                    return {'state': 'running', 'detail': 'Kullanıcının cihaz HTTP isteği sürüyor.'}
            return {'state': 'ready', 'detail': 'Kullanıcı onaylı cihaz kaydı var; gerçek cihaz sınanmadı.'}
        if record['kind'] == 'program':
            with _LOCK:
                if (owner, ident) in _RUNNING:
                    return {'state': 'running', 'detail': 'Kullanıcının yerel programı çalışıyor.'}
            try:
                _program(record['program'])
            except ValueError:
                return {'state': 'not_connected', 'detail': 'Seçilen program kurulu değil veya yürütülemiyor.'}
            return {'state': 'ready', 'detail': 'Kullanıcı onaylı yerel program kaydı var; gerçek PC sınanmadı.'}
        return {'state': 'ready', 'detail': 'Kullanıcı onaylı araç kaydı var; canlı servis sınanmadı.'}
    except Exception:
        _record_failure('modules/tool_wizard.py:status')
        return {'state': 'error', 'detail': 'Bu kullanıcı için araç kaydı doğrulanamadı.'}


def _cancel(owner, ident):
    try:
        service_store.identity(owner)
        kind = _load(owner)[ident]['kind']
        if kind == 'device':
            return {'cancelled': False, 'detail': 'Cihaz durdurma protokolü tanımlı değil; fiziksel durma doğrulanmadı.'}
        if kind == 'program':
            if _decision(owner, ident, 'local_reversible') != 'allow':
                return {'cancelled': False, 'detail': 'Yerel iptal izni verilmedi.'}
            with _LOCK:
                process = _RUNNING.get((owner, ident))
                if process is not None and process.poll() is None:
                    process.terminate()
                    return {'cancelled': True, 'detail': 'Başlatılan sürece durdurma iletildi; çıkış henüz doğrulanmadı.'}
            return {'cancelled': False, 'detail': 'Bu kullanıcı için çalışan yerel araç işi yok.'}
        return {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'}
    except Exception:
        _record_failure('modules/tool_wizard.py:cancel')
        return {'cancelled': False, 'detail': 'Araç kullanıcısı doğrulanamadı.'}


def contracts(owner):
    result = {}
    for ident, record in _load(owner).items():
        result[ident] = {'id': ident, 'name': record['name'], 'area': 'cihaz', 'icon': 'terminal' if record['kind'] == 'program' else 'globe',
                         'actions': [{'id': 'invoke', 'name': 'Çalıştır' if record['kind'] == 'program' else 'Veriyi oku', 'desc': 'Kullanıcının açıkça onayladığı araç girişi.',
                                      'class': record['class'], 'params': record['params']}],
                         'status': lambda ident=ident: _status(owner, ident),
                         'cancel': lambda ident=ident: _cancel(owner, ident)}
        if record['kind'] == 'device':
            result[ident]['icon'] = 'plug'
            result[ident]['actions'][0]['name'] = 'Fiziksel komut'
            result[ident]['actions'].append({'id': 'read', 'name': 'Durumu oku', 'desc': 'Sabit cihaz adresinden GET okuması.',
                                             'class': 'read', 'params': {}})
    return result
