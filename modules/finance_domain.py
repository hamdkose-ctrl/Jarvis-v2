"""Finance domain sözleşmesi (Faz 3-A): dallar, sınır ve kod göçü planı.

Yalnız sabit veri ve statik denetim. Fiyat okumaz, ağa çıkmaz, model çağırmaz,
dosya yazmaz ve hiçbir yolu çağırmaz. Karar kaydı:
docs/architecture/JARVIS_FINANCE_DOMAIN_DECISION.md; ayrıntılı sözleşme:
docs/architecture/JARVIS_FINANCE_DOMAIN_CONTRACT_V1.md.

Dört dal vardır: veri, alarm (takip listesi dahil), analiz, kaynak doğrulama.
Hiçbiri para, emir, hesap ya da dış alıcıya teslim etkisi taşımaz. Bildirimin
kullanıcıya iletilmesi Finance değil Communication'ın işidir; Finance yalnız
bildirim metnini üretir.
"""
from __future__ import annotations

import ast
from pathlib import Path

VERSION = 1
DOMAIN = 'finance'

# Finance'in kullanabileceği tek izin/etki sınıfları. money_credential, message_out,
# publish, external_write ve diğerleri bu domain'de hiçbir dalda yer almaz.
ALLOWED_PERMISSION_CLASSES = frozenset({'read', 'local_reversible'})
ALLOWED_EFFECT_POLICIES = frozenset({'read_only', 'local_reversible'})

BRANCHES = {
    'data': {
        'name': 'Veri: kur, piyasa, kripto, gram altın, BIST',
        'permission_class': 'read',
        'effect_policy': 'read_only',
        'modules': ('modules/finance.py', 'modules/tool_finance.py'),
        'entry_points': ('modules/finance.py:request_from_slots', 'modules/finance.py:answer_request',
                         'modules/finance.py:rates', 'modules/finance.py:dated_rate'),
        'invariants': (
            'Yalnız kamuya açık, anahtarsız ve ücretsiz kaynak okunur; okuma public_sources.fetch üzerinden yapılır.',
            'Kaynak yanıtından yalnız sayı ve tarih alınır; kaynak metni modele gitmez.',
            'Her cevapta kaynak adı ve veri zamanı/gecikmesi yazılır.',
        ),
    },
    'alarm': {
        'name': 'Alarm ve takip listesi',
        'permission_class': 'local_reversible',
        'effect_policy': 'local_reversible',
        'modules': ('modules/finance_alerts.py', 'modules/finance_alert_store.py',
                    'modules/finance_alert_schedule.py', 'modules/finance_alert_runner.py',
                    'modules/finance_alert_commands.py', 'modules/finance_watchlist.py', 'modules/finance_alert_tick.py'),
        'entry_points': ('modules/finance_alerts.py:evaluate', 'modules/finance_alert_runner.py:run_once',
                         'modules/finance_alert_commands.py:execute_typed', 'modules/finance_alert_schedule.py:notification_text'),
        'invariants': (
            'Yalnız kullanıcının kendi DATA_DIR kaydı yazılır (kural, durum, takip listesi); dış kayıt değişmez.',
            'Eşik değerlendirmesi modelsizdir ve emir, alım-satım ya da transfer başlatmaz.',
            'Finance yalnız bildirim metnini üretir; kime, hangi kanaldan iletileceği Communication sınırındadır.',
        ),
    },
    'analysis': {
        'name': 'Analiz: hesaplama, karşılaştırma, CSV gelir/gider',
        'permission_class': 'read',
        'effect_policy': 'read_only',
        'modules': ('modules/finance_analysis.py',),
        'entry_points': ('modules/finance_analysis.py:csv_summary',),
        'invariants': (
            'Girdi yalnız kullanıcının izinli alanındaki dosya veya Finance veri dalının çıktısıdır.',
            'Sonuç kişisel yatırım/ödeme kararı, öneri ya da kesin getiri iddiası değildir.',
            'Kaynak dosyası analiz boyunca değişmez (sha256 ile doğrulanır).',
        ),
    },
    'source_verification': {
        'name': 'Kaynak, tarih ve evidence doğrulaması',
        'permission_class': 'read',
        'effect_policy': 'read_only',
        'modules': (),
        'entry_points': ('modules/finance.py:dated_rate', 'modules/finance.py:_safe_xml'),
        'invariants': (
            'Kaynak yanıtı istenen varlık/para birimi ve tarihle eşleşmezse sonuç reddedilir.',
            'Kanıt en az kaynak adresi, veri tarihi, okuma zamanı ve gövde özeti (sha256) taşır.',
            'Kaynak içeriği izin, hedef ya da yürütme yetkisi vermez.',
        ),
    },
}

# Karar belgesindeki domain sınırı tablosu. Bilinmeyen tür fail-closed reddedilir.
BOUNDARY = {
    'market_data': {'owner': 'finance', 'permission_class': 'read', 'state': 'open'},
    'analysis': {'owner': 'finance', 'permission_class': 'read', 'state': 'open'},
    'alarm_rule': {'owner': 'finance', 'permission_class': 'local_reversible', 'state': 'open'},
    'alarm_delivery': {'owner': 'communication', 'permission_class': 'local_reversible', 'state': 'open'},
    'send_to_person': {'owner': 'communication', 'permission_class': 'message_out', 'state': 'open'},
    'publish': {'owner': 'communication', 'permission_class': 'publish', 'state': 'open'},
    'account_read': {'owner': 'finance', 'permission_class': 'money_credential', 'state': 'closed'},
    'money_effect': {'owner': 'finance', 'permission_class': 'money_credential', 'state': 'closed'},
}

# Finance kodunun geçmiş/açık göç kayıtları. Tamamlanan kayıtlar tarihi kanıttır;
# yalnız açık kayıtların kaynak konumu FIN-003 ile zorunlu tutulur.
MIGRATION = (
    {'step': '3-D', 'branch': 'alarm', 'location': 'modules/watcher.py:loop',
     'target': 'modules/watcher.py:loop', 'status': 'completed',
     'note': 'Bildirim teslimi Communication tarafında kalır; ntfy başlığı finans alarmı olarak ayrıldı.'},
)

# Finance modülleri bu modülleri içe aktaramaz: teslim/yayın/mesaj Communication'ındır.
COMMUNICATION_MODULES = frozenset({
    'notify', 'outbox', 'message_inbox', 'publish_services', 'publish_policy',
    'tool_mail', 'mail_content', 'mail_attachments', 'social_reads', 'git_publish',
})
# Finance modülleri izin ve grant kayıtlarını değiştiremez.
PERMISSION_WRITERS = frozenset({'permission_grants', 'permission_policy'})


def branch_of(module_path: str) -> str | None:
    """Bir modülün sahibi olan Finance dalı; Finance'e ait değilse None."""
    for name, branch in BRANCHES.items():
        if module_path in branch['modules']:
            return name
    return None


def route(kind: str) -> dict:
    """İş türünün sahibi ve izin sınıfı; kapalı ya da bilinmeyen tür reddedilir."""
    row = BOUNDARY.get(kind)
    if row is None:
        raise ValueError('Bilinmeyen finans iş türü.')
    if row['state'] != 'open':
        raise PermissionError('Bu finans işi kapalı: hesap, kimlik bilgisi ve para hareketi yolu yok.')
    return dict(row, kind=kind)


def owned_modules() -> tuple[str, ...]:
    return tuple(path for branch in BRANCHES.values() for path in branch['modules'])


def validate() -> list[str]:
    """Sözleşmenin kendi içinde tutarlı olduğunu denetler; hata listesi döner."""
    from modules.permission_gate import CLASSES
    errors = []
    seen = set()
    for name, branch in BRANCHES.items():
        if branch['permission_class'] not in ALLOWED_PERMISSION_CLASSES:
            errors.append(f'{name}: izin sınıfı Finance için açık değil.')
        if branch['effect_policy'] not in ALLOWED_EFFECT_POLICIES:
            errors.append(f'{name}: etki politikası Finance için açık değil.')
        if not branch['entry_points'] or not branch['invariants']:
            errors.append(f'{name}: giriş noktası ve kural gerekli.')
        for path in branch['modules']:
            if path in seen:
                errors.append(f'{path}: birden fazla dala bağlı.')
            seen.add(path)
    for kind, row in BOUNDARY.items():
        if row['permission_class'] not in CLASSES:
            errors.append(f'{kind}: bilinmeyen izin sınıfı.')
        if row['owner'] == DOMAIN and row['state'] == 'open' and row['permission_class'] not in ALLOWED_PERMISSION_CLASSES:
            errors.append(f'{kind}: Finance açık işi izinli sınıf dışında.')
    if BOUNDARY['money_effect']['state'] != 'closed' or BOUNDARY['account_read']['state'] != 'closed':
        errors.append('Para ve hesap yolu kapalı kalmalı.')
    for row in MIGRATION:
        if row['branch'] not in BRANCHES:
            errors.append(f"{row['location']}: bilinmeyen dal.")
        if row.get('status', 'open') not in {'open', 'completed'}:
            errors.append(f"{row['location']}: bilinmeyen göç durumu.")
    return errors


def _defined(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    return {node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def _imported(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.rsplit('.', 1)[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module == 'modules':
                names.update(alias.name for alias in node.names)
            elif node.module and node.module.startswith('modules.'):
                names.add(node.module.rsplit('.', 1)[-1])
    return names


def check(root=None) -> list[dict]:
    """Finance modüllerinin sınırı aşmadığını statik olarak denetler; kod çalıştırmaz.

    - Finance modülü Communication veya izin yazan modül içe aktaramaz.
    - tool_finance sözleşmesindeki her eylem izinli sınıfta olmalıdır.
    - Göç planındaki her konum hâlâ tanımlı olmalıdır (taşındıysa plan güncellenir).
    """
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    issues = []
    for rel in owned_modules():
        path = base / rel
        if not path.is_file():
            issues.append({'rule': 'FIN-000', 'path': rel, 'message': 'Sözleşmedeki Finance modülü yok.'})
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for name in sorted(_imported(tree) & (COMMUNICATION_MODULES | PERMISSION_WRITERS)):
            issues.append({'rule': 'FIN-001', 'path': rel,
                           'message': f'Finance modülü {name} modülünü içe aktaramaz; teslim/izin Finance dışındadır.'})
        if rel == 'modules/tool_finance.py':
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values):
                        if (isinstance(key, ast.Constant) and key.value == 'class' and isinstance(value, ast.Constant)
                                and value.value not in ALLOWED_PERMISSION_CLASSES):
                            issues.append({'rule': 'FIN-002', 'path': rel,
                                           'message': f'Finans aracı {value.value} sınıfında eylem açamaz.'})
    for row in MIGRATION:
        if row.get('status', 'open') == 'completed':
            continue
        rel, symbol = row['location'].split(':', 1)
        path = base / rel
        if not path.is_file() or symbol not in _defined(path):
            issues.append({'rule': 'FIN-003', 'path': rel,
                           'message': f'Açık göç planındaki {row["location"]} artık yok; MIGRATION güncellenmeli.'})
    for name, branch in BRANCHES.items():
        for entry in branch['entry_points']:
            rel, symbol = entry.split(':', 1)
            path = base / rel
            if not path.is_file() or symbol not in _defined(path):
                issues.append({'rule': 'FIN-004', 'path': rel,
                               'message': f'{name} dalının giriş noktası {entry} bulunamadı.'})
    return issues
