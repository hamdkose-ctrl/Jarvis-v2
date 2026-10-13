"""Account adapters for the task engine. No implicit login or write operations."""
import hashlib
import json
import re
import time
from modules import llm, privacy, requests_state

SERVICES = {
    'gmail': {'operations': ('list_unread', 'read_message','list_attachments','read_attachment'), 'implementation': 'google_oauth_readonly'},
    'telegram': {'operations': ('list_updates',), 'implementation': 'telegram_bot'},
    'whatsapp': {'operations': ('list_inbox',), 'implementation': 'signed_webhook_inbox'},
    'youtube': {'operations': ('channel_stats','list_comments'), 'implementation': 'google_oauth_readonly'},
    'instagram': {'operations': ('profile_stats','list_comments'), 'implementation': 'meta_professional'},
}


def validate_input(data):
    if not isinstance(data, dict) or set(data) - {'service', 'operation', 'limit', 'message_id', 'index','resource_id','attachment_index'}:
        raise ValueError('Hesap aracı girdisi geçersiz.')
    for key in ('service', 'operation'):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'[a-z_]{1,40}', value):
            raise ValueError('Servis/işlem adı geçersiz.')
    if data['service'] not in SERVICES:
        raise ValueError('Bilinmeyen hesap servisi.')
    limit = data.get('limit', 5)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Mail listesi sınırı 1–20 olmalı.')
    if data['operation'] in ('list_attachments','read_attachment'):
        if data['service']!='gmail' or 'index' in data or 'limit' in data or not isinstance(data.get('message_id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}',data['message_id']):raise ValueError('Ek okuma için kesin Gmail mail kimliği gerekli.')
        if data['operation']=='read_attachment' and (type(data.get('attachment_index')) is not int or not 1<=data['attachment_index']<=20):raise ValueError('Ek sıra numarası 1–20 olmalı.')
    elif data['operation'] == 'read_message':
        if 'limit' in data or ('message_id' in data) == ('index' in data):
            raise ValueError('Mail okumada tek message_id veya liste index gerekli.')
        if 'message_id' in data and (not isinstance(data['message_id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', data['message_id'])):
            raise ValueError('Mail kimliği geçersiz.')
        if 'index' in data and (type(data['index']) is not int or not 1 <= data['index'] <= 20):
            raise ValueError('Mail sıra numarası 1–20 olmalı.')
    elif 'message_id' in data or 'index' in data:
        raise ValueError('Bu işlem mail seçimi kabul etmez.')
    if 'attachment_index' in data and data['operation']!='read_attachment':raise ValueError('Bu işlem ek seçimi kabul etmez.')
    if data['operation']=='list_comments':
        resource=data.get('resource_id')
        pattern=r'[A-Za-z0-9_-]{11}' if data['service']=='youtube' else r'[0-9]{1,30}' if data['service']=='instagram' else ''
        if not pattern or not isinstance(resource,str) or not re.fullmatch(pattern,resource):raise ValueError('Yorum okuma için kesin video/medya kimliği gerekli.')
    elif 'resource_id' in data:raise ValueError('Bu işlem kaynak kimliği kabul etmez.')
    return dict(data)


def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def render_snapshot(snapshot):
    if snapshot['operation'] in ('list_attachments','read_attachment'):
        from modules import mail_attachments
        return mail_attachments.render(snapshot)
    if snapshot['operation'] == 'read_message':
        item = snapshot['message']
        return (f"Mail kimliği: {item['id']}\nGönderen: {item['from']}\nKonu: {item['subject']}\n\n" + item['body']
                + ('\n[Gövde uzunluk sınırında kesildi; tamamı okunmadı.]' if item['truncated'] else ''))
    items = snapshot['items']
    text = ('Listelenen okunmamış mail başlıkları:\n' + '\n'.join(
        f"{i['from']}: {i['subject']}" + (f" (kimlik: {i['id']})" if snapshot.get('show_ids') else '') for i in items)) if items else 'Bu sorguda okunmamış mail bulunmadı.'
    if snapshot['has_more']:
        text += '\nDaha fazla sonuç var; bu liste ilk sayfadır.'
    return text


def run(owner, data, dependencies=None):
    data = validate_input(data)
    # Require explicit execution identity, not the UI's global active profile.
    if not isinstance(owner, str) or not re.fullmatch(r'[\w-]{1,100}', owner) or llm._key_context.get() != owner:
        raise PermissionError('Hesap ve görev kullanıcısı eşleşmiyor.')
    requests_state.check()
    service = data['service']
    if data['operation'] not in SERVICES[service]['operations']:
        return {'state': 'unavailable', 'text': 'Bu servis işlemi ortak görev katmanında henüz desteklenmiyor.',
                'service': service, 'operation': data['operation']}
    if service=='whatsapp':
        from modules import message_inbox
        return message_inbox.read(owner,data.get('limit',5))
    if blocked := privacy.blocked('web'):
        return {'state': 'blocked', 'text': blocked}
    if service!='gmail':
        from modules import social_reads
        return social_reads.run(owner,data)
    if data['operation'] == 'read_message' and 'index' in data:
        from modules import task_results
        candidates = [out for out in (dependencies or {}).values() if isinstance(out, dict)
                      and isinstance(out.get('snapshot'), dict) and out['snapshot'].get('operation') == 'list_unread']
        if len(candidates) != 1:
            raise ValueError('Sıralı mail seçimi tek doğrulanmış listeye bağlı olmalı.')
        task_results.verify(candidates[0], owner=owner)
        items = candidates[0]['snapshot']['items']
        if data['index'] > len(items):
            raise ValueError('İstenen sırada mail yok.')
        data = {**data, 'message_id': items[data['index'] - 1]['id']}
    from modules import google_api
    try:
        svc = google_api._service('gmail', 'v1', interactive=False)
        messages = svc.users().messages()
        if data['operation'] in ('list_attachments','read_attachment'):
            from modules import mail_attachments
            msg=messages.get(userId='me',id=data['message_id'],format='full').execute()
            requests_state.check()
            if not isinstance(msg,dict) or msg.get('id')!=data['message_id'] or not isinstance(msg.get('payload'),dict):raise ValueError('Ek mail yanıtı kimlikle eşleşmiyor.')
            parts=mail_attachments.parts(msg['payload'])
            snapshot={'owner':owner,'service':'gmail','operation':data['operation'],'message_id':data['message_id'],'fetched_at':time.time()}
            if data['operation']=='list_attachments':snapshot.update(items=[i for i,p in parts[:20]],has_more=len(parts)>20)
            else:
                index=data['attachment_index']
                if index>len(parts):raise ValueError('Seçilen sırada ek yok.')
                item,part=parts[index-1]
                if not item['supported']:return {'state':'unavailable','text':'Bu ek desteklenmiyor: yalnız en fazla 256 KiB TXT/CSV/Markdown metni okunur.'}
                snapshot['attachment']={**item,**mail_attachments.read(messages,data['message_id'],part)}
            return {'state':'done','text':render_snapshot(snapshot),'snapshot':snapshot,'sha256':digest(snapshot)}
        if data['operation'] == 'read_message':
            from modules import mail_content
            msg = messages.get(userId='me', id=data['message_id'], format='full').execute()
            requests_state.check()
            if not isinstance(msg, dict) or msg.get('id') != data['message_id'] or not isinstance(msg.get('payload'), dict):
                raise ValueError('Gmail mail yanıtı kimlikle eşleşmiyor.')
            h = mail_content.headers(msg['payload'])
            item = {'id': msg['id'], 'from': h.get('from', ''), 'subject': h.get('subject', '(konusuz)'),
                    **mail_content.extract(msg['payload'])}
            snapshot = {'owner': owner, 'service': 'gmail', 'operation': 'read_message',
                        'fetched_at': time.time(), 'message': item}
            return {'state': 'done', 'text': render_snapshot(snapshot), 'snapshot': snapshot, 'sha256': digest(snapshot)}
        result = messages.list(userId='me', q='is:unread in:inbox',
                               maxResults=data.get('limit', 5)).execute()
        if not isinstance(result, dict):
            raise ValueError('Gmail liste yanıtı geçersiz.')
        ids = result.get('messages', [])
        if not isinstance(ids, list) or len(ids) > data.get('limit', 5):
            raise ValueError('Gmail liste yanıtı geçersiz.')
        items = []
        seen = set()
        for item in ids:
            requests_state.check()
            mid = item.get('id') if isinstance(item, dict) else None
            if not isinstance(mid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', mid) or mid in seen:
                raise ValueError('Gmail mesaj kimliği geçersiz.')
            seen.add(mid)
            msg = messages.get(userId='me', id=mid, format='metadata',
                               metadataHeaders=['From', 'Subject']).execute()
            if not isinstance(msg, dict) or msg.get('id') != mid:
                raise ValueError('Gmail mesaj yanıtı kimlikle eşleşmiyor.')
            payload = msg.get('payload')
            if not isinstance(payload, dict) or not isinstance(payload.get('headers', []), list):
                raise ValueError('Gmail başlık yanıtı geçersiz.')
            headers = payload.get('headers', [])
            values = {}
            for header in headers:
                if not isinstance(header, dict) or not isinstance(header.get('name'), str) or not isinstance(header.get('value'), str):
                    raise ValueError('Gmail başlık yanıtı geçersiz.')
                values[header['name'].lower()] = header['value'][:2000]
            items.append({'id': mid, 'from': values.get('from', ''),
                          'subject': values.get('subject', '(konusuz)')})
        snapshot = {'owner': owner, 'service': service, 'operation': data['operation'],
                    'fetched_at': time.time(), 'query': 'is:unread in:inbox',
                    'limit': data.get('limit', 5), 'items': items,
                    'has_more': bool(result.get('nextPageToken')), 'show_ids': True}
        return {'state': 'done', 'text': render_snapshot(snapshot), 'snapshot': snapshot, 'sha256': digest(snapshot)}
    except requests_state.Cancelled:
        raise
    except PermissionError:
        return {'state': 'unavailable', 'text': 'Gmail izni gerekli. Mevcut Gmail bağlantısından bağlan veya izni yenile.'}
    except ImportError:
        return {'state': 'unavailable', 'text': 'Mevcut Google bağlantısının paketleri eksik.'}


def capabilities():
    lines = ['Ortak hesap araçları (bağlantı durumu değildir):']
    for service, spec in SERVICES.items():
        operations = ', '.join(spec['operations']) or 'henüz desteklenmiyor'
        lines.append(service + ': ' + operations)
    lines.append('WhatsApp yalnız imzalı webhook ile alınmış yerel kayıtları okur; eski geçmişe erişmez. Yazma/yayın ayrı publish worker ve yetki gerektirir.')
    return '\n'.join(lines)
