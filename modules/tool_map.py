"""Aktif kullanıcı için araç ve izin politikası görünümü; işlem yürütmez."""
from modules import permission_audit, permission_gate, permission_grants, permission_policy
from modules import service_store, tool_contract
from modules.diagnostics import record_failure as _record_failure

_LABELS = {
    'read': ('Okuma', 'Salt okunur işlemler.'),
    'local_reversible': ('Geri alınabilir', 'Yerel geri alınabilir işlemler.'),
    'local_destructive': ('Yıkıcı', 'Yerel yıkıcı işlemler.'),
    'external_write': ('Dış hesap yazısı', 'Özel dış hesaptaki kesin kaydı oluşturur, değiştirir veya siler.'),
    'message_out': ('Gönderim', 'Alıcıya bağlı gönderim izni ayrıca gerekir.'),
    'publish': ('Yayın', 'Yayın onayı ayrıca gerekir.'),
    'money_credential': ('Para ve kimlik', 'Bu sınıfın politikası kilitlidir.'),
    'system_config': ('Sistem ayarı', 'Bu sınıfın politikası kilitlidir.'),
    'physical': ('Fiziksel işlem', 'Gerçek cihaz etkisi her seferinde somut onay ister.'),
}
_BUILTINS = {'desktop': ('Masaüstü', 'cihaz', 'monitor'),
             'browser': ('Tarayıcı', 'cihaz', 'globe'),
             'outbox': ('Gönderim', 'iletisim', 'mail')}


def _catalog():
    tools = {}
    for ident, (name, area, icon) in _BUILTINS.items():
        tools[ident] = {'id': ident, 'name': name, 'area': area, 'icon': icon,
                        'state': 'ready', 'detail': 'İzin politikaları',
                        'actions': [{'id': cls, 'name': _LABELS.get(cls, (cls, ''))[0],
                                     'desc': _LABELS.get(cls, (cls, ''))[1], 'class': cls}
                                    for cls in sorted(permission_gate.CLASSES)]}
    for ident, contract in tool_contract.load_all().items():
        if ident in tools:
            raise ValueError('Araç kimliği yerleşik yolla çakışıyor.')
        description = tool_contract.describe(contract)
        status = description.pop('status')
        actions = []
        seen = set()
        for item in description['actions']:
            action = item.get('id', item['class'])
            if not isinstance(action, str) or not action or action in seen:
                raise ValueError('Araç eylemi belirsiz.')
            seen.add(action)
            actions.append({'id': action, 'name': item.get('name', action),
                            'desc': item.get('desc', ''), 'class': item['class']})
        tools[ident] = {'id': ident, 'name': description['name'],
                        'area': description.get('area', 'cihaz'), 'icon': description.get('icon', 'gear'),
                        'state': status['state'], 'detail': status['detail'], 'actions': actions}
    return tools


def _via(ident, tools):
    # Politika deposu yol adında '-' kabul etmez; çakışan adlar kesin reddedilir.
    via = ident.replace('-', '_')
    if any(other != ident and other.replace('-', '_') == via for other in tools):
        raise ValueError('Politika yolu belirsiz.')
    return via


def snapshot(owner):
    """Mesaj içeriği veya alıcılar olmadan kullanıcının Harita görünümü."""
    try:
        service_store.identity(owner)
        tools = _catalog()
        recent = permission_audit.recent(owner)
        grants = permission_grants.load(owner)['message_out']
        until = max(grants.values(), default=None)
        for ident, tool in tools.items():
            via = _via(ident, tools)
            tool['last'] = [{key: row[key] for key in ('t', 'decision', 'class', 'via')}
                            for row in recent if row['via'] == via][:10]
            for action in tool['actions']:
                cls = action['class']
                action['policy'] = ('locked' if cls in permission_policy.LOCKED
                                    else permission_policy.get(owner, via, cls))
                action['until'] = until if cls == 'message_out' else None
        placeholders = [{'area': 'cihaz', 'name': name} for ident, name in
                        (('printer', 'Yazıcı'), ('slicer', 'Dilimleyici'), ('cad', 'CAD')) if ident not in tools]
        return {'tools': list(tools.values()), 'placeholders': placeholders}
    except Exception:
        _record_failure('modules/tool_map.py:snapshot')
        return None


def set_policy(owner, tool, action, policy):
    """Yalnız bilinen, kilitli olmayan sınıfın politikasını değiştirir."""
    try:
        service_store.identity(owner)
        if not all(isinstance(value, str) for value in (tool, action, policy)) or policy not in permission_policy.VALUES:
            return None
        tools = _catalog()
        if tool not in tools:
            return None
        selected = next((row for row in tools[tool]['actions'] if row['id'] == action), None)
        if selected is None or selected['class'] in permission_policy.LOCKED:
            return None
        permission_policy.set(owner, _via(tool, tools), selected['class'], policy)
        return {'ok': True}
    except Exception:
        _record_failure('modules/tool_map.py:set_policy')
        return None
