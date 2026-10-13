"""Bounded bot/account statistics reads; no fallback to browser or personal sessions."""
import time
from config import DATA_DIR
from modules import publish_services as services, account_tools
_record_failure=services._record_failure


def youtube(interactive=False):
    from modules import google_api
    from googleapiclient.discovery import build
    creds=google_api._creds(DATA_DIR/'google_youtube_read_token.json',
        ['https://www.googleapis.com/auth/youtube.readonly'],interactive)
    return build('youtube','v3',credentials=creds,cache_discovery=False)


def _get(url,headers):
    import requests
    try:
        response=requests.get(url,headers=headers,timeout=30,allow_redirects=False)
        response.raise_for_status();result=response.json()
    except Exception:
        _record_failure('modules/social_reads.py:get')
        raise RuntimeError('Servis okuma yanıtı alınamadı.') from None
    if not isinstance(result,dict):raise ValueError('Servis okuma yanıtı geçersiz.')
    return result


def run(owner,data):
    service=data['service'];operation=data['operation'];items=[]
    if service=='telegram':
        config=services.configuration(owner,service)
        import re
        token=config.get('bot_token');chat=config.get('read_chat_id')
        if not isinstance(token,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token) or not isinstance(chat,str) or not re.fullmatch(r'-?[0-9]{1,20}',chat):
            raise PermissionError('Telegram bot ve okunacak kesin sohbet kimliği gerekli.')
        request={'limit':data.get('limit',5),'timeout':0,'allowed_updates':['message']}
        if config.get('consume_updates') is True:
            from modules import bot_updates
            key,last=bot_updates.cursor(owner,token)
            if last is not None:request['offset']=last+1
        result=services._http('https://api.telegram.org/bot'+token+'/getUpdates',request)
        if result.get('ok') is not True or not isinstance(result.get('result'),list):raise ValueError('Telegram güncelleme yanıtı geçersiz.')
        for update in result['result'][:data.get('limit',5)]:
            msg=update.get('message',{}) if isinstance(update,dict) else {}
            if str(msg.get('chat',{}).get('id'))!=chat:continue
            if not isinstance(msg.get('text'),str):continue
            items.append({'id':str(update['update_id']),'text':msg['text'][:4096],'chat_id':chat})
        if config.get('consume_updates') is True:
            bot_updates.save(owner,key,result['result'][:data.get('limit',5)],chat)
    elif service=='youtube':
        svc=youtube()
        if operation=='list_comments':
            owned=svc.channels().list(part='id',mine=True,maxResults=20).execute()
            video=svc.videos().list(part='snippet',id=data['resource_id']).execute()
            own_ids={i['id'] for i in owned.get('items',[])}
            videos=video.get('items',[])
            if len(videos)!=1 or videos[0].get('id')!=data['resource_id'] or videos[0].get('snippet',{}).get('channelId') not in own_ids:raise PermissionError('Video bu OAuth kullanıcısının kanalına ait değil.')
            result=svc.commentThreads().list(part='snippet',videoId=data['resource_id'],maxResults=data.get('limit',5),order='time',textFormat='plainText').execute()
            for item in result.get('items',[])[:data.get('limit',5)]:
                comment=item['snippet']['topLevelComment'];s=comment['snippet']
                if not isinstance(s.get('textDisplay'),str):raise ValueError('YouTube yorum metni geçersiz.')
                items.append({'id':comment['id'],'text':s['textDisplay'][:10000],'author':str(s.get('authorDisplayName',''))[:2000],'published_at':s.get('publishedAt','')})
        else:
            result=svc.channels().list(part='id,snippet,statistics',mine=True,maxResults=20).execute()
            for item in result.get('items',[])[:20]:
                stats=item.get('statistics',{})
                items.append({'id':item['id'],'text':str(item.get('snippet',{}).get('title',''))[:2000],
                              'statistics':{k:str(v)[:100] for k,v in stats.items() if k in ('viewCount','subscriberCount','videoCount','hiddenSubscriberCount')}})
    elif service=='instagram':
        config=services.configuration(owner,service)
        import re
        version=config.get('api_version');user=config.get('ig_user_id');token=config.get('access_token')
        if not isinstance(version,str) or not re.fullmatch(r'v[0-9]{1,2}\.0',version) or not isinstance(user,str) or not user.isdigit() or not isinstance(token,str) or not token:
            raise PermissionError('Instagram profesyonel hesap yapılandırması gerekli.')
        base='https://graph.facebook.com/'+version+'/';headers={'Authorization':'Bearer '+token}
        if operation=='list_comments':
            media=_get(base+data['resource_id']+'?fields=id,owner',headers)
            if str(media.get('id'))!=data['resource_id'] or str(media.get('owner',{}).get('id'))!=user:raise PermissionError('Instagram medya sahibi eşleşmiyor.')
            result=_get(base+data['resource_id']+'/comments?fields=id,text,username,timestamp&limit='+str(data.get('limit',5)),headers)
            for item in result.get('data',[])[:data.get('limit',5)]:
                if not isinstance(item.get('id'),str) or not isinstance(item.get('text'),str):raise ValueError('Instagram yorum kaydı geçersiz.')
                items.append({'id':item['id'],'text':item['text'][:10000],'author':str(item.get('username',''))[:2000],'published_at':item.get('timestamp','')})
        else:
            result=_get(base+user+'?fields=id,username,followers_count,media_count',headers)
            if str(result.get('id'))!=user:raise ValueError('Instagram okuma hesabı eşleşmiyor.')
            items=[{'id':user,'text':str(result.get('username',''))[:2000],
                    'statistics':{k:str(result[k])[:100] for k in ('followers_count','media_count') if k in result}}]
    else:raise ValueError('Sosyal okuma desteklenmiyor.')
    snapshot={'owner':owner,'service':service,'operation':operation,'fetched_at':time.time(),'items':items,'scope':'bounded_account_read'}
    if operation=='list_comments':
        snapshot['resource_id']=data['resource_id'];snapshot['has_more']=bool(result.get('nextPageToken') or result.get('paging',{}).get('next'))
    return {'state':'done','text':render(snapshot),'snapshot':snapshot,'sha256':account_tools.digest(snapshot)}


def render(snapshot):
    import json
    return snapshot['service']+' hesap okuma kaydı (sınırlı sonuç):\n'+json.dumps(snapshot['items'],ensure_ascii=False)+('\nİlk sayfa; daha fazla sonuç var.' if snapshot.get('has_more') else '')
