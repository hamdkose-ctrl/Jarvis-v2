"""Ortak izin kapısının saf karar çekirdeği; mevcut yürütme yollarına bağlı değildir."""
import time

READ = 'read'
LOCAL_REVERSIBLE = 'local_reversible'
LOCAL_DESTRUCTIVE = 'local_destructive'
MESSAGE_OUT = 'message_out'
PUBLISH = 'publish'
MONEY_CREDENTIAL = 'money_credential'
SYSTEM_CONFIG = 'system_config'

ALLOW = 'allow'
ASK = 'ask'
DENY = 'deny'

CLASSES = {
    READ, LOCAL_REVERSIBLE, LOCAL_DESTRUCTIVE, MESSAGE_OUT,
    PUBLISH, MONEY_CREDENTIAL, SYSTEM_CONFIG,
}
VIAS = {'outbox', 'desktop', 'browser', 'file', 'system'}


def _result(decision, action_class, reason):
    return {'decision': decision, 'class': action_class, 'reason': reason}


def _same_target(expected, actual):
    if expected == '*' or actual == '*':
        return False
    if '@' in expected and '@' in actual:
        return expected.casefold() == actual.casefold()
    return expected == actual


def _active_message_grant(grants, target, now):
    if not isinstance(grants, dict):
        return False
    rows = grants.get(MESSAGE_OUT)
    if not isinstance(rows, dict) or target == '*':
        return False
    if not isinstance(now, (int, float)) or isinstance(now, bool):
        return False
    for granted_target, expires in rows.items():
        if (not isinstance(granted_target, str)
                or not isinstance(expires, (int, float)) or isinstance(expires, bool)):
            continue
        if _same_target(granted_target, target) and expires > now:
            return True
    return False


def decide(action: dict, grants: dict | None = None, now: float | None = None) -> dict:
    """Verilen eylem için yalnız girdilere bakarak allow/ask/deny kararı üretir."""
    if not isinstance(action, dict):
        return _result(ASK, '', 'Eylem bilgisi belirsiz; onay gerekli.')
    action_class = action.get('class')
    target = action.get('target')
    via = action.get('via')
    if not isinstance(action_class, str) or action_class not in CLASSES:
        return _result(ASK, action_class if isinstance(action_class, str) else '', 'Eylem sınıfı belirsiz; onay gerekli.')
    if not isinstance(target, str):
        return _result(ASK, action_class, 'Hedef belirsiz; onay gerekli.')
    if via not in VIAS:
        return _result(ASK, action_class, 'İşlem yolu belirsiz; onay gerekli.')
    if action_class in {MESSAGE_OUT, PUBLISH} and not target.strip():
        return _result(ASK, action_class, 'Gönderim hedefi gerekli; onay gerekli.')

    if action_class == READ:
        return _result(ALLOW, action_class, 'Salt okuma güvenli.')
    if action_class == LOCAL_REVERSIBLE:
        return _result(ALLOW, action_class, 'Yerel geri alınabilir işlem.')
    if action_class == LOCAL_DESTRUCTIVE:
        return _result(ASK, action_class, 'Yıkıcı yerel işlem onay ister.')
    if action_class == MESSAGE_OUT:
        current = time.time() if now is None else now
        if _active_message_grant(grants, target, current):
            return _result(ALLOW, action_class, 'Hedef için süreli izin geçerli.')
        return _result(ASK, action_class, 'Mesaj gönderimi hedef onayı ister.')
    if action_class == PUBLISH:
        return _result(ASK, action_class, 'Yayınlama her zaman onay ister.')
    if action_class == MONEY_CREDENTIAL:
        return _result(DENY, action_class, 'Para ve kimlik bilgisi işlemleri kapalı.')

    never = grants.get('apps_never') if isinstance(grants, dict) else None
    if isinstance(never, (list, tuple, set)) and _never_hit(never, target):
        return _result(DENY, action_class, 'Bu sistem hedefi kalıcı olarak yasak.')
    return _result(ASK, action_class, 'Sistem ayarı onay ister.')

def _never_hit(never, target):
    def norm(value):
        text = str(value).strip().casefold()
        return text[:-4] if text.endswith('.exe') else text
    return norm(target) in {norm(item) for item in never}
