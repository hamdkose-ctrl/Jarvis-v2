"""Account adapters for the task engine. No implicit login or write operations."""
import hashlib
import json
import re
import time
from datetime import datetime
from modules import llm, privacy, requests_state
from modules.diagnostics import record_failure as _record_failure

SERVICES = {
    'gmail': {'operations': ('list_unread', 'read_message','list_attachments','read_attachment','read_thread'), 'implementation': 'google_oauth_readonly'},
    'calendar': {'operations': ('suggest_slot',), 'implementation': 'google_oauth_readonly'},
    'telegram': {'operations': ('list_updates',), 'implementation': 'telegram_bot'},
    'whatsapp': {'operations': ('list_inbox',), 'implementation': 'signed_webhook_inbox'},
    'youtube': {'operations': ('channel_stats','list_comments'), 'implementation': 'google_oauth_readonly'},
    'instagram': {'operations': ('profile_stats','list_comments'), 'implementation': 'meta_professional'},
    'drive': {'operations': ('list_files','read_document','read_sheet'), 'implementation': 'google_drive_readonly'},
}


def _network_unavailable(exc):
    from modules import failure_policy
    return failure_policy.network_unavailable(exc)

def validate_input(data):
    if not isinstance(data, dict) or set(data) - {'service', 'operation', 'limit', 'message_id', 'index','resource_id','attachment_index','query','file_id','cell_range','thread_id','window_start','window_end','minutes'}:
        raise ValueError('Hesap aracı girdisi geçersiz.')
    for key in ('service', 'operation'):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'[a-z_]{1,40}', value):
            raise ValueError('Servis/işlem adı geçersiz.')
    if data['service'] not in SERVICES:
        raise ValueError('Bilinmeyen hesap servisi.')
    if data['service'] == 'drive':
        operation = data['operation']
        if operation == 'list_files':
            if not isinstance(data.get('query', ''), str) or len(data.get('query', '')) > 500:
                raise ValueError('Drive arama ifadesi geçersiz.')
        elif operation == 'read_document':
            if not isinstance(data.get('file_id'), str): raise ValueError('Drive dosya kimliği gerekli.')
        elif operation == 'read_sheet':
            if not isinstance(data.get('file_id'), str) or not isinstance(data.get('cell_range'), str):
                raise ValueError('Sheets için dosya kimliği ve aralık gerekli.')
        if operation != 'list_files' and 'query' in data: raise ValueError('Bu Drive işlemi arama ifadesi kabul etmez.')
    if data['service'] == 'gmail' and data['operation'] == 'read_thread':
        if set(data) != {'service', 'operation', 'thread_id'} or not isinstance(data.get('thread_id'), str):
            raise ValueError('Gmail konuşma okuma için yalnız thread_id gerekli.')
    if data['service'] == 'calendar':
        if data['operation'] != 'suggest_slot' or set(data) != {'service', 'operation', 'window_start', 'window_end', 'minutes'}:
            raise ValueError('Takvim önerisi için başlangıç, bitiş ve dakika gerekli.')
        if not all(isinstance(data.get(key), str) and len(data[key]) <= 80 for key in ('window_start', 'window_end')):
            raise ValueError('Takvim zaman aralığı geçersiz.')
        if type(data.get('minutes')) is not int or not 15 <= data['minutes'] <= 480:
            raise ValueError('Takvim öneri süresi geçersiz.')
    limit = data.get('limit', 5)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Mail listesi sınırı 1–20 olmalı.')
    if data['operation'] in ('list_attachments','read_attachment'):
        if data['service']!='gmail' or 'limit' in data or ('message_id' in data)==('index' in data):raise ValueError('Ek okuma için kesin Gmail mail kimliği veya doğrulanmış liste sırası gerekli.')
        if 'message_id' in data and (not isinstance(data['message_id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}',data['message_id'])):raise ValueError('Ek mail kimliği geçersiz.')
        if 'index' in data and (type(data['index']) is not int or not 1<=data['index']<=20):raise ValueError('Ek mail sırası 1–20 olmalı.')
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
    if service in {'gmail', 'calendar'} and data['operation'] in {'read_thread', 'suggest_slot'}:
        from modules import gmail_calendar_readonly, google_api
        try:
            if data['operation'] == 'read_thread':
                gmail = google_api._service('gmail', 'v1', interactive=False)
                thread = gmail_calendar_readonly.read_thread(gmail, data['thread_id'])
                snapshot = {'owner': owner, 'service': service, 'operation': data['operation'],
                            'thread': thread, 'fetched_at': time.time()}
                return {'state': 'done', 'text': 'Gmail konuşması salt-okunur okundu.',
                        'snapshot': snapshot, 'sha256': digest(snapshot)}
            start = datetime.fromisoformat(data['window_start'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(data['window_end'].replace('Z', '+00:00'))
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError('Takvim zamanları saat dilimi içermeli.')
            calendar = google_api._service('calendar', 'v3', interactive=False)
            rows = calendar.events().list(calendarId='primary', timeMin=start.isoformat(),
                timeMax=end.isoformat(), singleEvents=True, orderBy='startTime', maxResults=50).execute().get('items', [])
            busy = []
            for row in rows:
                begin = row.get('start', {}).get('dateTime') if isinstance(row, dict) else None
                finish = row.get('end', {}).get('dateTime') if isinstance(row, dict) else None
                if begin and finish:
                    busy.append((datetime.fromisoformat(begin), datetime.fromisoformat(finish), row.get('summary', '(adsız)')))
            suggestion = gmail_calendar_readonly.suggest_slot(start, end, busy, minutes=data['minutes'])
            suggestion = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in suggestion.items()}
            snapshot = {'owner': owner, 'service': service, 'operation': data['operation'],
                        'suggestion': suggestion, 'fetched_at': time.time()}
            return {'state': 'done', 'text': suggestion['note'], 'snapshot': snapshot, 'sha256': digest(snapshot)}
        except PermissionError:
            return {'state': 'unavailable', 'text': 'Gmail/Takvim okuma izni gerekli; yalnız salt-okunur bağlantıyı yetkilendir.'}
    if service == 'drive':
        from modules import drive_readonly
        try:
            drive, docs, sheets = drive_readonly.services(interactive=False)
            if data['operation'] == 'list_files':
                items = drive_readonly.list_files(drive, query=data.get('query', ''), limit=data.get('limit', 5))
                snapshot = {'owner': owner, 'service': service, 'operation': data['operation'], 'items': items, 'fetched_at': time.time()}
            elif data['operation'] == 'read_document':
                document = drive_readonly.read_document(docs, data['file_id'])
                snapshot = {'owner': owner, 'service': service, 'operation': data['operation'], 'document': document, 'fetched_at': time.time()}
            else:
                sheet = drive_readonly.read_sheet(sheets, data['file_id'], data['cell_range'], max_rows=data.get('limit', 5))
                snapshot = {'owner': owner, 'service': service, 'operation': data['operation'], 'sheet': sheet, 'fetched_at': time.time()}
            text = 'Drive okuma tamamlandı.' if data['operation'] == 'list_files' else 'Drive içeriği okundu.'
            return {'state': 'done', 'text': text, 'snapshot': snapshot, 'sha256': digest(snapshot)}
        except PermissionError:
            return {'state': 'unavailable', 'text': 'Drive okuma izni gerekli; yalnız salt-okunur Drive bağlantısını yetkilendir.'}
    if service!='gmail':
        from modules import social_reads
        return social_reads.run(owner,data)
    if data['operation'] in ('read_message','list_attachments','read_attachment') and 'index' in data:
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
            if data['operation']=='list_attachments' or not parts:
                # A verified empty attachment list is a normal result, including read requests.
                snapshot.update(operation='list_attachments',items=[i for i,p in parts[:20]],has_more=len(parts)>20)
            else:
                index=data['attachment_index']
                if index>len(parts):raise ValueError('Seçilen sırada ek yok.')
                item,part=parts[index-1]
                if not item['supported']:return {'state':'unavailable','text':'Bu ek desteklenmiyor: TXT/CSV/Markdown 256 KiB; PDF/DOCX/XLSX/PPTX 4 MiB sınırında okunur.'}
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
            return {'state': 'done', 'text': render_snapshot(snapshot),'snapshot': snapshot,'sha256': digest(snapshot)}
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
        return {'state': 'done','text': render_snapshot(snapshot),'snapshot': snapshot,'sha256': digest(snapshot)}
    except requests_state.Cancelled:
        raise
    except PermissionError:
        return {'state': 'unavailable', 'text': 'Gmail izni gerekli. Mevcut Gmail bağlantısından bağlan veya izni yenile.'}
    except ImportError:
        return {'state': 'unavailable', 'text': 'Mevcut Google bağlantısının paketleri eksik.'}
    except Exception as exc:
        _record_failure('modules/account_tools.py:run')
        if _network_unavailable(exc):
            return {'state':'unavailable','text':('Gmail şu anda Google sunucularına ağ/DNS üzerinden ulaşamıyor. '
                    'Mevcut hesap izni korunuyor; bağlantı düzeldiğinde yeniden dene.'),
                    'service':'gmail','operation':data['operation']}
        raise


def capabilities():
    lines = ['Ortak hesap araçları (bağlantı durumu değildir):']
    for service, spec in SERVICES.items():
        operations = ', '.join(spec['operations']) or 'henüz desteklenmiyor'
        lines.append(service + ': ' + operations)
    lines.append('WhatsApp yalnız imzalı webhook ile alınmış yerel kayıtları okur; eski geçmişe erişmez. Yazma/yayın ayrı publish worker ve yetki gerektirir.')
    return '\n'.join(lines)
