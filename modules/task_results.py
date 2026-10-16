"""Local evidence checks for durable task outputs; no model or service calls."""
from pathlib import Path
import hashlib
import re
import math

VERSION = 1
STATES = {'done', 'failed', 'blocked', 'approval', 'unavailable'}


def file_digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Kanıt dosyası eksik, boş veya sembolik bağ.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check(kind, output):
    if not isinstance(output, dict) or output.get('state') != 'done':
        raise ValueError('Görev sonucu tamamlanmış değil.')
    if kind in ('research', 'writer', 'coder'):
        if not isinstance(output.get('text'), str) or not output['text'].strip():
            raise ValueError('Görev çıktısı boş.')
    if kind == 'research':
        from modules.browser_agent import _url
        _url(output.get('source', ''))
        chars = output.get('source_chars')
        if type(chars) is not int or chars < 80:
            raise ValueError('Araştırmanın kaynak okuma kanıtı eksik.')
        if output.get('news_article'):
            from modules import research_evidence
            research_evidence.news_receipt(output)
    elif kind == 'writer':
        digest = output.get('sha256', '')
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Raporun içerik özeti eksik.')
        if file_digest(output.get('file', '')) != digest:
            raise ValueError('Rapor dosyası değişmiş veya eksik.')
        if 'news_report_evidence' in output:
            from modules import research_evidence
            evidence=output['news_report_evidence']
            expected=research_evidence.news_report(evidence['sources'])+research_evidence.unavailable_footer(evidence['unavailable'])
            if output['text']!=expected or Path(output['file']).read_text(encoding='utf-8')!=expected:
                raise ValueError('Haber raporu tarih, kaynak ve alıntı kaydıyla eşleşmiyor.')
    elif kind == 'coder':
        if output.get('draft') is not True or output.get('test_ok') is not True:
            raise ValueError('Kod taslağı ve geçerli başarılı test kanıtı gerekli.')
        files=output.get('files')
        if not isinstance(files,list) or not files or not isinstance(output.get('owner'),str) or not output['owner']:
            raise ValueError('Kod teslim dosyaları ve sahibi eksik.')
        if any(not isinstance(item,dict) or file_digest(item.get('file',''))!=item.get('sha256') for item in files):
            raise ValueError('Kod teslim dosyası değişmiş veya eksik.')
        if output.get('file')!=files[0]['file'] or file_digest(output.get('test_log',''))!=output.get('test_log_sha256'):
            raise ValueError('Kod teslimi veya test günlüğü değişmiş.')
    elif kind == 'browser':
        steps = output.get('steps')
        if not isinstance(steps, list) or not steps or any(
            not isinstance(step, dict) or step.get('verified') is not True for step in steps
        ):
            raise ValueError('Tarayıcı adımlarının doğrulama kanıtı eksik.')
        page = output.get('page')
        if not isinstance(page, dict):
            raise ValueError('Tarayıcı sayfa kaydı eksik.')
        from modules.browser_agent import _url
        _url(page.get('url', ''))
        digest = file_digest(output.get('image', ''))
        if output.get('image_sha256') != digest:
            raise ValueError('Tarayıcı ekran dosyası değişmiş veya kanıt özeti eksik.')
    elif kind == 'verify':
        checks = output.get('checks')
        if not isinstance(checks, dict) or not checks or any(v is not True for v in checks.values()):
            raise ValueError('Bağımlı sonuçların doğrulama kanıtı eksik.')
    elif kind == 'account':
        from modules import account_tools
        snapshot = output.get('snapshot')
        if isinstance(snapshot,dict) and snapshot.get('service') in ('telegram','youtube','instagram','whatsapp'):
            from modules import social_reads
            service=snapshot['service'];items=snapshot.get('items')
            if snapshot.get('operation') not in account_tools.SERVICES[service]['operations'] or snapshot.get('scope')!='bounded_account_read':raise ValueError('Sosyal okuma kapsamı geçersiz.')
            if not isinstance(snapshot.get('owner'),str) or not snapshot['owner'] or type(snapshot.get('fetched_at')) not in (int,float) or not math.isfinite(snapshot['fetched_at']) or snapshot['fetched_at']<=0:raise ValueError('Sosyal okuma kimliği/zamanı eksik.')
            if not isinstance(items,list) or len(items)>20 or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] or not isinstance(item.get('text'),str) for item in items):raise ValueError('Sosyal okuma kanıtı geçersiz.')
            if output.get('sha256')!=account_tools.digest(snapshot) or output.get('text')!=social_reads.render(snapshot):raise ValueError('Sosyal okuma kaydı değişmiş.')
            return True
        if not isinstance(snapshot, dict) or snapshot.get('service') != 'gmail' or snapshot.get('operation') not in ('list_unread', 'read_message','list_attachments','read_attachment'):
            raise ValueError('Hesap sonucu desteklenen okumaya ait değil.')
        if not isinstance(snapshot.get('owner'), str) or not snapshot['owner']:
            raise ValueError('Hesap sonucu kullanıcı kaydı eksik.')
        if snapshot['operation'] in ('list_attachments','read_attachment'):
            from modules import mail_attachments
            mail_attachments.verify(snapshot)
            if output.get('sha256')!=account_tools.digest(snapshot) or output.get('text')!=account_tools.render_snapshot(snapshot):raise ValueError('Ek okuma kaydı değişmiş.')
            return True
        if snapshot['operation'] == 'read_message':
            from modules import mail_content
            item = snapshot.get('message')
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', item['id']):
                raise ValueError('Mail kimlik kanıtı eksik.')
            if any(not isinstance(item.get(key), str) for key in ('from', 'subject', 'body')) or not item['body'].strip() or len(item['body']) > mail_content.MAX_TEXT:
                raise ValueError('Mail gövde kanıtı geçersiz.')
            if type(item.get('truncated')) is not bool or item.get('format') not in ('plain', 'html_text'):
                raise ValueError('Mail okuma kapsamı eksik.')
            ts = snapshot.get('fetched_at')
            if type(ts) not in (int, float) or not math.isfinite(ts) or ts <= 0:
                raise ValueError('Mail okuma zamanı eksik.')
            if output.get('sha256') != account_tools.digest(snapshot) or output.get('text') != account_tools.render_snapshot(snapshot):
                raise ValueError('Mail gövde kaydı değişmiş.')
            return True
        limit = snapshot.get('limit')
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('Hesap sonucu liste sınırı geçersiz.')
        items = snapshot.get('items')
        if not isinstance(items, list) or len(items) > limit or any(
            not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
            or any(not isinstance(item.get(key), str) for key in ('from', 'subject')) for item in items
        ):
            raise ValueError('Hesap mesaj kanıtı geçersiz.')
        if len({item['id'] for item in items}) != len(items):
            raise ValueError('Hesap mesaj kimlikleri tekil olmalı.')
        if type(snapshot.get('fetched_at')) not in (int, float) or not math.isfinite(snapshot['fetched_at']) or snapshot['fetched_at'] <= 0 or snapshot.get('query') != 'is:unread in:inbox' or type(snapshot.get('has_more')) is not bool:
            raise ValueError('Hesap okuma kaydı eksik.')
        if 'show_ids' in snapshot and type(snapshot['show_ids']) is not bool:
            raise ValueError('Mail kimlik gösterimi geçersiz.')
        if output.get('sha256') != account_tools.digest(snapshot):
            raise ValueError('Hesap okuma kaydı değişmiş.')
        if output.get('text') != account_tools.render_snapshot(snapshot):
            raise ValueError('Hesap sonuç metni okuma kaydıyla eşleşmiyor.')
    elif kind == 'publish':
        receipt=output.get('receipt')
        if not isinstance(receipt,dict) or receipt.get('scope')!='provider_accepted' or not isinstance(receipt.get('remote_id'),str) or not receipt['remote_id']:
            raise ValueError('Gerçek servis işlem kimliği eksik.')
        from modules import publish_services
        if receipt.get('service') not in publish_services.OPERATIONS or not isinstance(receipt.get('destination'),str):
            raise ValueError('Servis/hedef kanıtı eksik.')
        if not isinstance(output.get('payload_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',output['payload_sha256']):
            raise ValueError('Gönderim içerik kaydı eksik.')
    elif kind == 'media':
        from modules import media_tools
        if file_digest(output.get('file',''))!=output.get('sha256'):raise ValueError('Video dosyası değişmiş.')
        if media_tools.probe(output['file'])!=output.get('media'):raise ValueError('Video akış kanıtı değişmiş.')
    else:
        raise ValueError('Bilinmeyen sonuç türü.')
    return True


def seal(kind, output):
    if not isinstance(output, dict) or output.get('state') not in STATES:
        raise ValueError('Araç geçerli bir görev sonucu döndürmedi.')
    output = dict(output)
    if output['state'] == 'done':
        if kind == 'browser':
            output['image_sha256'] = file_digest(output.get('image', ''))
        check(kind, output)
        output['verification'] = {'version': VERSION, 'agent': kind, 'scope': 'execution_evidence'}
    return output


def verify(output, owner=None):
    metadata = output.get('verification', {}) if isinstance(output, dict) else {}
    if not isinstance(metadata, dict) or metadata.get('version') != VERSION:
        raise ValueError('Sonucun doğrulama kaydı eksik; eski kayıt başarı kanıtı olarak kullanılamaz.')
    checked = check(metadata.get('agent'), output)
    if owner is not None and metadata.get('agent') == 'coder' and output.get('owner') != owner:
        raise PermissionError('Kod sonucu farklı kullanıcıya ait.')
    if owner is not None and metadata.get('agent') == 'account' and output.get('snapshot', {}).get('owner') != owner:
        raise PermissionError('Hesap sonucu farklı kullanıcıya ait.')
    if owner is not None and metadata.get('agent') == 'publish':
        from modules import outbox
        saved=outbox.get(owner,output.get('id'))
        if saved['state']!='accepted' or saved['receipt']!=output['receipt'] or saved['digest']!=output['payload_sha256']:
            raise ValueError('Gönderim kanıtı kalıcı servis kaydıyla eşleşmiyor.')
    return checked
