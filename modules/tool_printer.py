"""Kullanıcıya özel OctoPrint/Moonraker; her fiziksel komut ayrı onay ister."""
from contextvars import ContextVar
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests

from config import DATA_DIR
from modules import llm, permission_audit, permission_gate, permission_policy, service_store
from modules.diagnostics import record_failure as _diagnostic_failure
from modules.publish_services import _read_private_json, _write_private_json

ROOT = DATA_DIR / 'printer'
_STOP_OWNER = ContextVar('printer_stop_owner', default=None)
_ACTIONS = ('start', 'pause', 'resume', 'cancel')


def _record_failure(context):
    # Transport exceptions can contain private device addresses. Never log them.
    try:
        raise RuntimeError('Yazıcı işlemi güvenli biçimde durduruldu.') from None
    except RuntimeError:
        _diagnostic_failure(context)


def _path(owner):
    if not isinstance(owner, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', owner):
        raise ValueError('Geçersiz kullanıcı.')
    service_store.identity(owner)
    path = ROOT / (owner + '.json')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in (path, *path.parents)):
        raise ValueError('Yazıcı yolu sembolik bağ olamaz.')
    return path


def _validate(backend, address, key):
    if backend not in ('octoprint', 'moonraker') or not isinstance(address, str) or len(address) > 500:
        raise ValueError('Geçersiz yazıcı bağlantısı.')
    url = urlsplit(address)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment or url.path not in ('', '/')
            or any(c.isspace() or ord(c) < 32 for c in address)):
        raise ValueError('Yalnız açıkça verilen HTTP(S) yazıcı kök adresi kabul edilir.')
    _ = url.port  # Validate port before any network request.
    if not isinstance(key, str) or not 1 <= len(key) <= 1024 or any(ord(c) < 32 or ord(c) > 126 for c in key):
        raise ValueError('Geçersiz yazıcı anahtarı.')
    return {'backend': backend, 'address': address.rstrip('/'), 'key': key}


def configure(owner, backend, address, key):
    """Adres kullanıcı tarafından verilir; keşif/tarama veya otomatik bağlantı yoktur."""
    path = _path(owner)
    data = _validate(backend, address, key)
    _write_private_json(path, data)
    return {'ok': True, 'backend': backend, 'address': '***', 'key': '***'}


def _config(owner):
    data = _read_private_json(_path(owner), migrate=False)
    return _validate(data.get('backend'), data.get('address'), data.get('key'))


def _http(config, method, endpoint, payload=None):
    # Inherited proxy/CA settings and TLS verification remain enabled. Redirects
    # are rejected so the API key never follows a server-controlled destination.
    with requests.request(method, config['address'] + endpoint,
                          headers={'X-Api-Key': config['key']}, json=payload,
                          timeout=(3, 5), allow_redirects=False, stream=True) as response:
        if not 200 <= response.status_code < 300:
            raise ValueError('Yazıcı isteği kabul edilmedi.')
        raw = bytearray()
        for chunk in response.iter_content(8192):
            raw.extend(chunk)
            if len(raw) > 262144:
                raise ValueError('Yazıcı yanıtı çok büyük.')
        if method == 'GET':
            import json
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('Geçersiz yazıcı durumu.')
            return data
        return None


def _state(config):
    if config['backend'] == 'octoprint':
        value = _http(config, 'GET', '/api/job').get('state')
        running, ready = ('Printing', 'Paused', 'Pausing', 'Cancelling', 'Resuming'), ('Operational',)
    else:
        data = _http(config, 'GET', '/printer/objects/query?print_stats')
        value = data.get('result', {}).get('status', {}).get('print_stats', {}).get('state')
        running, ready = ('printing', 'paused'), ('standby', 'complete', 'cancelled')
    if value in running:
        return {'state': 'running', 'detail': 'Yazıcı devam eden baskı bildiriyor.'}
    if value in ready:
        return {'state': 'ready', 'detail': 'Yazıcı etkin baskı bildirmiyor.'}
    return {'state': 'error', 'detail': 'Yazıcı hazır olduğunu doğrulamadı.'}


def status():
    owner = llm._key_context.get()
    if not owner:
        return {'state': 'not_connected', 'detail': 'Kullanıcı seçilmedi.'}
    try:
        path = _path(owner)
        if not path.is_file():
            return {'state': 'not_connected', 'detail': 'Bu kullanıcı için yazıcı bağlantısı yok.'}
        return _state(_config(owner))
    except Exception:
        _record_failure('modules/tool_printer.py:status')
        return {'state': 'error', 'detail': 'Yazıcı durumu doğrulanamadı.'}


def run(owner, action, *, filename='', approve=False):
    try:
        service_store.identity(owner)
        if action not in _ACTIONS or not isinstance(approve, bool):
            raise ValueError('Geçersiz yazıcı eylemi.')
        if action == 'start' and (not isinstance(filename, str) or not re.fullmatch(r'[\w .-]{1,150}\.gcode', filename) or '..' in filename):
            raise ValueError('Yalnız seçilmiş üst düzey G-code dosyası kabul edilir.')
        result = permission_gate.decide({'class': 'physical', 'target': action, 'via': 'system'})
        decision, reason = permission_policy.apply(owner, 'printer', 'physical', result['decision'], result['reason'])
        if decision not in ('allow', 'ask', 'deny'):
            raise ValueError('Geçersiz izin kararı.')
        permission_audit.record(owner, decision, 'physical', action, 'system', reason)
        if decision == 'deny':
            return {'state': 'blocked', 'detail': reason}
        # Even an erroneous ALLOW from the gate cannot supply physical consent.
        if not approve:
            return {'state': 'approval', 'detail': 'Bu fiziksel yazıcı işlemi için somut onay gerekli.'}
        config = _config(owner)
        if config['backend'] == 'octoprint':
            if action == 'start':
                # Select only an already uploaded file, then start it. No upload/download.
                from urllib.parse import quote
                _http(config, 'POST', '/api/files/local/' + quote(filename, safe=''), {'command': 'select', 'print': True})
            else:
                payload = {'command': 'cancel'} if action == 'cancel' else {'command': 'pause', 'action': action}
                _http(config, 'POST', '/api/job', payload)
        else:
            _http(config, 'POST', '/printer/print/' + action, {'filename': filename} if action == 'start' else {})
        observed = _state(config)
        if action == 'cancel' and observed['state'] != 'ready':
            return {'state': 'unverified', 'detail': 'İptal komutu iletildi; durma henüz doğrulanmadı.'}
        return {'state': 'done', 'detail': 'Durma geri okumayla doğrulandı.' if action == 'cancel' else 'Komut kabul edildi; fiziksel sonuç sınanmadı.'}
    except Exception:
        _record_failure('modules/tool_printer.py:run')
        return {'state': 'blocked', 'detail': 'Yazıcı işlemi tamamlanamadı; otomatik tekrar yapılmadı.'}


def cancel():
    owner = llm._key_context.get()
    return run(owner, 'cancel', approve=bool(owner and _STOP_OWNER.get() == owner))


def cancel_running(owner):
    """Yalnız açık Durdur düğmesinden: o kullanıcının çalışan araçlarını iptal et."""
    token = None
    try:
        service_store.identity(owner)
        token = _STOP_OWNER.set(owner)
        from modules import tool_contract
        results = {}
        for contract in tool_contract.load_all().values():
            try:
                if contract['status']().get('state') == 'running':
                    results[contract['id']] = contract['cancel']()
            except Exception:
                _record_failure('modules/tool_printer.py:cancel_tool')
                results[contract['id']] = {'state': 'error', 'detail': 'Araç iptali doğrulanamadı.'}
        return results
    except Exception:
        _record_failure('modules/tool_printer.py:cancel_running')
        return {'error': 'Çalışan araçların iptali doğrulanamadı.'}
    finally:
        if token is not None:
            _STOP_OWNER.reset(token)


CONTRACT = {
    'id': 'printer', 'name': 'Yazıcı', 'area': 'cihaz', 'icon': 'printer',
    'actions': [{'id': action, 'name': name, 'desc': 'Her çağrıda fiziksel onay isteyen yazıcı komutu.',
                 'class': 'physical', 'params': {'filename': 'str'} if action == 'start' else {}}
                for action, name in zip(_ACTIONS, ('Baskıyı başlat', 'Baskıyı duraklat', 'Baskıyı sürdür', 'Baskıyı iptal et'))],
    'status': status, 'cancel': cancel,
}
