"""Typed adapters for monitoring, capability discovery and domain data."""
from __future__ import annotations
import json
import re
from modules import service_store

TOOLS={
 'monitor':'Proaktif kaynak takibi. operation=add(url,terms:list,interval?:300..86400,label?)|list|events(limit?)|pause/resume/remove(id)|check(id). Yalnız açık takip isteğiyle kaydet; ilk tarama eski haberleri yeni saymaz.',
 'capability':'Yeni API/MCP referansı. operation=discover(query)|list|assess(id)|specialists|bind(id,endpoint,parameters:{ad:tür})|read(id,parameters)|unbind(id). bind yalnız açık istek ve somut onayla sabit, anahtarsız GET bağlar; MCP kodu/ücretli hesap kurmaz.',
 'data':'Alan verileri. operation=exchange(base,quote,date?)|headlines(url)|finance_csv/store_csv(path,columns,decimal?:"."|",")|social(service,account_operation,resource_id?,limit?). finance columns={amount,kind,date?}; store={sku,quantity,minimum?,price?}; değerler gerçek CSV sütun adlarıdır. Mağaza/banka kaynağı değiştirilmez.',
}


def validate(kind,data):
    if kind not in TOOLS or not isinstance(data,dict) or not isinstance(data.get('operation'),str):raise ValueError('Alan aracı işlemi gerekli.')
    if len(json.dumps(data,ensure_ascii=False))>24000:raise ValueError('Alan aracı girdisi fazla uzun.')
    op=data['operation']
    schemas={
      'monitor':{'add':({'url','terms'},{'interval','label'}),'list':(set(),set()),'events':(set(),{'limit'}),
                 'pause':({'id'},set()),'resume':({'id'},set()),'remove':({'id'},set()),'check':({'id'},set())},
      'capability':{'discover':({'query'},set()),'list':(set(),set()),'assess':({'id'},set()),'specialists':(set(),set()),
                    'bind':({'id','endpoint','parameters'},set()),'read':({'id','parameters'},set()),'unbind':({'id'},set())},
      'data':{'exchange':({'base','quote'},{'date'}),'headlines':({'url'},set()),
              'finance_csv':({'path','columns'},{'decimal'}),'store_csv':({'path','columns'},{'decimal'}),
              'social':({'service','account_operation'},{'resource_id','limit'})}}
    if op not in schemas[kind]:raise ValueError('Alan aracı işlemi kayıtlı değil.')
    required,optional=schemas[kind][op]
    if not required.issubset(data) or set(data)-required-optional-{'operation'}:raise ValueError('Alan aracında eksik/bilinmeyen alan var.')
    for key,value in data.items():
        if key in {'operation','terms','parameters','columns','interval','limit'}:continue
        if not isinstance(value,str) or not value.strip() or len(value)>2048 or '\x00' in value:raise ValueError('Alan aracı metin girdisi geçersiz.')
    if 'parameters' in data and not isinstance(data['parameters'],dict):raise ValueError('Parametre nesnesi gerekli.')
    if 'columns' in data and not isinstance(data['columns'],dict):raise ValueError('Sütun eşleştirmesi gerekli.')
    if 'terms' in data:
        from modules.source_watch import _terms
        _terms(data['terms'])
    if 'interval' in data and (type(data['interval']) is not int or not 300<=data['interval']<=86400):raise ValueError('Takip aralığı geçersiz.')
    if 'limit' in data and (type(data['limit']) is not int or not 1<=data['limit']<=20):raise ValueError('Sonuç sınırı 1–20 olmalı.')
    return data


def replay_safe(kind,data):
    return (kind=='data' or kind=='monitor' and data['operation'] in {'list','events','check'} or
            kind=='capability' and data['operation'] in {'discover','list','assess','read','specialists'})


def checkpoint(runtime,kind,data):
    owner=runtime.profile.slug
    if kind=='monitor':
        from modules import source_watch
        return {'records':source_watch.rows(owner)}
    if kind=='capability' and data['operation'] in ('bind','unbind'):
        from modules import capability_hub
        return {'records':capability_hub.rows(owner)}
    return None


def reconcile(runtime,kind,data,identity,check):
    if not check:return None
    from modules.goal_tools import local_result
    owner=runtime.profile.slug;op=data['operation']
    if kind=='monitor':
        from modules import source_watch
        current=source_watch.rows(owner);before=check['records']
        if op=='add':
            from modules.public_sources import address
            added=next((r for r in current if r['id'] not in {b['id'] for b in before} and r['url']==address(data['url']) and r['terms']==data['terms']),None)
            if added:return local_result(owner,kind,'Yanıt kesildi; kaynak takibinin gerçekten kaydedildiğini doğruladım. Takip: '+added['id'],reconciled=True)
        selected=next((r for r in current if r['id']==data.get('id')),None)
        prior=next((r for r in before if r['id']==data.get('id')),None)
        if op=='remove' and prior and not selected:return local_result(owner,kind,'Kaynak takibinin kaldırıldığını doğruladım.',reconciled=True)
        if op in ('pause','resume') and selected and bool(selected['paused'])==(op=='pause'):
            return local_result(owner,kind,'Kaynak takibinin istenen durumunu doğruladım.',reconciled=True)
    if kind=='capability' and op in ('bind','unbind'):
        from modules import capability_hub
        row=next((r for r in capability_hub.rows(owner) if r['id']==data['id']),None)
        if not row:return None
        expected={'endpoint':data.get('endpoint'),'method':'GET','parameters':data.get('parameters'),'authentication':'none','code_installed':False}
        if (op=='bind' and row['binding']==expected) or (op=='unbind' and row['binding'] is None):
            return local_result(owner,kind,'Genel okuma bağlantısının istenen durumunu doğruladım.',reconciled=True)
    return None


def _human(kind,op,value):
    if isinstance(value,str):return value
    if kind=='monitor':
        if op=='add':return value['message']+'\nTakip: '+value.get('id',value.get('rule',{}).get('id',''))
        if op=='list':return '\n'.join(r['label']+' — '+('duraklatıldı' if r['paused'] else 'izleniyor')+'\n'+r['url'] for r in value['watches']) or 'Kayıtlı kaynak takibi yok.'
        if op=='events':
            from modules.source_watch import render
            return '\n\n'.join(render(e) for e in value['events']) or 'Henüz yeni konu eşleşmesi kaydedilmedi.'
        if op=='check':return 'Kaynağı kontrol ettim: '+value['rule']['label']+'\n'+value['rule']['url']+'\nYeni eşleşmeler kayıtlı bildirimlerde gösterilir; ilk tarama mevcut içerikleri baz alır.'
    if kind=='capability':
        if op in ('discover','list'):
            return '\n\n'.join(r['name']+' — '+r.get('description','')[:180]+'\nAday: '+r['id']+'\nBelge: '+r['url'] for r in value['candidates']) or 'Bu sorguda servis adayı bulunamadı.'
        if op=='assess':return 'Servisin belge sayfasını okuyabildim. İşlem, ücret/kota ve kimlik gereksinimi henüz doğrulanmış sayılmaz.\nKaynak: '+value['document_url']
        if op=='specialists':return '\n\n'.join(s['name']+': '+', '.join(t['tool']+' ('+t['readiness']+')' for t in s['tools']) for s in value['specialists'])
        if op=='read':return 'Bağlı genel API verisini okudum.\nKaynak: '+value['source']+'\n'+value['excerpt'][:1200]
        if op=='bind':return value['text']
    if op=='exchange':
        row=value['data'];return row['base']+'/'+row['quote']+': '+str(row['rate'])+'\nVeri tarihi: '+row['date']+'\n'+value['scope']+'\nKaynak: '+value['source']
    if op.endswith('_csv'):
        row=value['result']
        if op=='finance_csv':text='Gelir: '+row['income']+'\nGider: '+row['expense']+'\nNet: '+row['net']
        else:text='Ürün: '+str(row['products'])+'\nToplam stok: '+row['units']+'\nMinimum altında: '+str(row['below_minimum_count'])+' ürün'
        return str(value['rows'])+' veri satırını analiz ettim.\n'+text+'\n'+value['scope']
    if op=='headlines':return '\n\n'.join(row['title']+(' · '+row['published'] if row['published'] else '')+'\n'+row['url'] for row in value['items'][:10])
    return json.dumps(value,ensure_ascii=False,default=str)


def execute(runtime,kind,data,identity,approval=None):
    from modules.goal_tools import local_result,NotStarted,public_request
    from modules import privacy
    owner=runtime.profile.slug;service_store.identity(owner);validate(kind,data)
    op=data['operation'];request=identity.get('request','').casefold().replace('\u0307','')
    def clean(value):
        if isinstance(value,dict):return {k:('[gizlendi]' if re.search(r'key|token|secret|password|credential|authorization|parola|şifre',str(k),re.I) else clean(v)) for k,v in value.items()}
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,str):
            if value.lstrip().startswith(('{','[')):
                try:parsed=json.loads(value)
                except ValueError:parsed=None
                if isinstance(parsed,(dict,list)):return json.dumps(clean(parsed),ensure_ascii=False)
            return privacy.redact(public_request(value),force=True)
        return value
    def result(value,**extra):
        value=clean(value)
        if not isinstance(value,str):extra['structured']=value
        return local_result(owner,kind,_human(kind,op,value),**extra)
    if kind=='monitor':
        from modules import source_watch
        if op in {'add','pause','resume','remove'} and not re.search(r'takip|izle|bildir|haber ver',request):
            raise NotStarted('Kullanıcının açık hedefinde kaynak takibi değişikliği yok.')
        if op=='add':
            from modules.public_sources import address
            target=address(data['url']);explicit=[]
            for match in re.findall(r'https://[^\s<>|]+',identity.get('request','')):
                try:explicit.append(address(match.rstrip('.,!?)\"\'”')))
                except ValueError:continue
            known=any(target==entry['url'] and any(all(word in request for word in words) for words in entry['aliases'])
                      for entry in source_watch.KNOWN_SOURCES.values())
            if target not in explicit and not known:raise NotStarted('Takip kaynağı kullanıcı hedefindeki kesin adres veya konuya uyan kayıtlı resmî kaynak olmalı; kaynak metni izleme izni veremez.')
            existing=next((r for r in source_watch.rows(owner) if r['url']==target and r['terms']==data['terms']),None)
            if existing:
                if existing['interval']!=data.get('interval',600):raise NotStarted('Aynı kaynak ve konu farklı sıklıkla kayıtlı; mevcut takip değiştirilmedi.')
                return result({'message':'Bu kaynak/konu takibi zaten kayıtlı.','rule':existing})
            try:ident=source_watch.add(owner,data['url'],data['terms'],data.get('interval',600),data.get('label',''))
            except ValueError as exc:raise NotStarted(str(exc)) from None
            return result({'message':'Takip kaydedildi. İlk tarama mevcut içerikleri baz alır; yeni eşleşmeler Jarvis açıkken bildirilir.','id':ident})
        if op=='list':return result({'watches':source_watch.rows(owner)})
        if op=='events':return result({'events':source_watch.events(owner,data.get('limit',20))})
        selected=next((r for r in source_watch.rows(owner) if r['id']==data['id']),None)
        if not selected:raise NotStarted('Bu kullanıcıya ait kaynak takibi yok.')
        if op=='remove' and not approval:return {'state':'approval','text':'Kaynak takibi silinecek: '+selected['label']+'\n'+selected['url'],'id':data['id']}
        if op=='remove':source_watch.remove(owner,data['id']);return result('Seçilen kaynak takibini kaldırdım.')
        if op in ('pause','resume'):
            source_watch.pause(owner,data['id'],op=='pause');return result('Takip duraklatıldı.' if op=='pause' else 'Takip sürdürüldü.')
        if selected['paused']:raise NotStarted('Takip duraklatılmış; kontrol yapılmadı. Tek seferlik okuma için data headlines kullanılabilir.')
        if blocked:=privacy.blocked('web'):raise NotStarted(blocked)
        checked=source_watch.poll(owner,rule_id=data['id'],force=True)
        if checked is None:raise RuntimeError('Kaynak kontrolü başlamadı veya başka kontrol sürüyor.')
        current=next((r for r in source_watch.rows(owner) if r['id']==data['id']),None)
        if current is None:raise NotStarted('Takip kontrol sırasında kaldırıldı.')
        if current['error']:raise RuntimeError('Kaynak kontrolü tamamlanmadı: '+current['error'])
        return result({'rule':current,'events':source_watch.events(owner,20)})
    if kind=='capability':
        from modules import capability_hub,specialist_contracts
        if op=='discover':return result(capability_hub.discover(owner,data['query']))
        if op=='list':return result({'candidates':capability_hub.rows(owner)})
        if op=='assess':return result(capability_hub.assess(owner,data['id']))
        if op=='specialists':return result(specialist_contracts.describe(owner))
        if op=='read':return result(capability_hub.read(owner,data['id'],data['parameters']))
        if op=='bind':
            if not re.search(r'bağla|bagla|connect|kullanıma aç|kullanima ac',request):raise NotStarted('Kullanıcı açıkça servis bağlantısı istemedi; yalnız değerlendirme yapılabilir.')
            try:preview=capability_hub.public_binding(owner,data['id'],data['endpoint'],data['parameters'])
            except ValueError as exc:raise NotStarted(str(exc)) from None
            if not approval:return preview
            value=capability_hub.public_binding(owner,data['id'],data['endpoint'],data['parameters'],confirmed=approval is not None)
            return result(value) if value['state']=='done' else value
        if not re.search(r'kaldır|kaldir|sil|bağlantı.*kapat|baglanti.*kapat',request):raise NotStarted('Bağlantı kaldırma hedefte yok.')
        if not approval:return {'state':'approval','text':'Genel GET bağlantısı kaldırılacak: '+data['id'],'id':data['id']}
        capability_hub.unbind(owner,data['id']);return result('Genel okuma bağlantısı kaldırıldı.')
    from modules import domain_tools
    if op=='exchange':return result(domain_tools.exchange(owner,data['base'],data['quote'],data.get('date')))
    if op=='headlines':return result(domain_tools.headlines(owner,data['url']))
    if op in ('finance_csv','store_csv'):
        value=domain_tools.csv_analysis(owner,op.split('_')[0],data['path'],data['columns'],data.get('decimal','.'))
        return result(value,source_file=value['source_file'],source_sha256=value['source_sha256'])
    value=domain_tools.social(owner,data['service'],data['account_operation'],data.get('resource_id'),data.get('limit',10))
    if value['state']!='done':return value
    return result(value['text'],source_receipt=value['source_receipt'])
