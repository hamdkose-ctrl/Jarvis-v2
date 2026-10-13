"""Bounded Gmail attachment metadata and explicit plain-text reads."""
import base64
from email.message import Message
from pathlib import PurePosixPath
from modules import mail_content, requests_state

MAX_BYTES=262144
SUFFIXES={'.txt','.csv','.md'}
MIMES={'text/plain','text/csv','text/markdown','application/csv','application/octet-stream'}
DOCUMENT_MIMES={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation'}


def size_limit(name):
    return 4*1024*1024 if PurePosixPath(name.replace('\\','/')).suffix.lower() in DOCUMENT_MIMES else MAX_BYTES


def supported(name,mime,size):
    suffix=PurePosixPath(name.replace('\\','/')).suffix.lower()
    return size<=size_limit(name) and ((suffix in SUFFIXES and mime in MIMES) or (suffix in DOCUMENT_MIMES and mime in (DOCUMENT_MIMES[suffix],'application/octet-stream')))


def parts(payload):
    found=[];count=0
    def visit(part,depth):
        nonlocal count
        count+=1
        if count>256 or depth>16 or not isinstance(part,dict):raise ValueError('Ek MIME yapısı geçersiz veya çok büyük.')
        children=part.get('parts',[])
        if not isinstance(children,list):raise ValueError('Ek MIME parçaları geçersiz.')
        name=part.get('filename','')
        if not isinstance(name,str) or len(name)>500:raise ValueError('Ek adı geçersiz.')
        if name:
            body=part.get('body',{});mime=part.get('mimeType','')
            if not isinstance(body,dict) or not isinstance(mime,str) or type(body.get('size')) is not int or body['size']<0:raise ValueError('Ek metaverisi geçersiz.')
            suffix=PurePosixPath(name.replace('\\','/')).suffix.lower()
            found.append(({'index':len(found)+1,'filename':name,'mime':mime,'size':body['size'],
                           'supported':supported(name,mime,body['size'])},part))
            return
        for child in children:visit(child,depth+1)
    visit(payload,0)
    return found


def read(messages,mid,part):
    body=part['body'];encoded=body.get('data')
    if encoded is None:
        aid=body.get('attachmentId')
        if not isinstance(aid,str) or not aid or len(aid)>1000:raise ValueError('Ek kimliği eksik.')
        requests_state.check()
        result=messages.attachments().get(userId='me',messageId=mid,id=aid).execute()
        requests_state.check()
        if not isinstance(result,dict):raise ValueError('Ek yanıtı geçersiz.')
        encoded=result.get('data')
    limit=size_limit(part['filename'])
    if not isinstance(encoded,str) or len(encoded)>((limit+2)//3)*4+4:raise ValueError('Ek kodlaması sınırı aşıyor.')
    raw=base64.b64decode(encoded+'='*(-len(encoded)%4),altchars=b'-_',validate=True)
    if not raw or len(raw)>limit or len(raw)!=body['size']:raise ValueError('Ek boyutu doğrulanamadı.')
    suffix=PurePosixPath(part['filename'].replace('\\','/')).suffix.lower()
    if suffix in DOCUMENT_MIMES:
        from modules import attachment_documents
        result=attachment_documents.read(raw,suffix);requests_state.check();return result
    headers=mail_content.headers(part);message=Message();message['content-type']=headers.get('content-type',part['mimeType'])
    try:text=raw.decode(message.get_content_charset() or 'utf-8')
    except (UnicodeError,LookupError):raise ValueError('Ek metin kodlaması okunamadı.') from None
    if '\x00' in text or not text.strip():raise ValueError('Ek düz metin değil veya boş.')
    return {'body':text[:mail_content.MAX_TEXT],'truncated':len(text)>mail_content.MAX_TEXT}


def render(snapshot):
    if snapshot['operation']=='list_attachments':
        lines=[str(i['index'])+'. '+i['filename']+' · '+str(i['size'])+' bayt · '+('metin okuma destekleniyor' if i['supported'] else 'metin okuma desteklenmiyor/sınır aşılıyor') for i in snapshot['items']]
        return 'Mail ekleri ('+snapshot['message_id']+'):\n'+('\n'.join(lines) or 'Ek yok.')+('\n[İlk 20 ek gösterildi.]' if snapshot['has_more'] else '')
    item=snapshot['attachment']
    return 'Mail eki: '+item['filename']+' (mail: '+snapshot['message_id']+')\n\n'+item['body']+('\n[Metin sınırda kesildi; tamamı okunmadı.]' if item['truncated'] else '')


def verify(snapshot):
    import math,re
    if not isinstance(snapshot.get('message_id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}',snapshot['message_id']):raise ValueError('Ek mail kimliği eksik.')
    if type(snapshot.get('fetched_at')) not in (int,float) or not math.isfinite(snapshot['fetched_at']) or snapshot['fetched_at']<=0:raise ValueError('Ek okuma zamanı eksik.')
    items=snapshot.get('items') if snapshot['operation']=='list_attachments' else [snapshot.get('attachment')]
    if not isinstance(items,list) or len(items)>20:raise ValueError('Ek kayıt sınırı geçersiz.')
    for item in items:
        if not isinstance(item,dict) or type(item.get('index')) is not int or not 1<=item['index']<=256 or not isinstance(item.get('filename'),str) or not item['filename'] or len(item['filename'])>500 or not isinstance(item.get('mime'),str) or type(item.get('size')) is not int or item['size']<0 or type(item.get('supported')) is not bool:raise ValueError('Ek kaydı geçersiz.')
    if snapshot['operation']=='list_attachments':
        if type(snapshot.get('has_more')) is not bool or [i['index'] for i in items]!=list(range(1,len(items)+1)):raise ValueError('Ek liste kapsamı geçersiz.')
    else:
        item=items[0]
        if item['supported'] is not True or not 0<item['size']<=size_limit(item['filename']) or not supported(item['filename'],item['mime'],item['size']) or not isinstance(item.get('body'),str) or not item['body'].strip() or len(item['body'])>mail_content.MAX_TEXT or type(item.get('truncated')) is not bool:raise ValueError('Ek metin kanıtı geçersiz.')
