"""User-owned specialist directory and views over the existing execution journals.

Directory entries describe routing, never grant permissions or execute imported code.
All work still goes through goal_tools/task_agents and their existing boundaries.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from config import DATA_DIR
import release_guard
from modules import privacy, service_store

ROOT = DATA_DIR / 'teams'
_LOCK = threading.RLock()
DEFAULTS = [
    {'id':'research','name':'Araştırma ve gündem','tags':['haber','gündem','araştır','kaynak'], 'tools':['research','browser','writer','data','monitor','capability','verify']},
    {'id':'finance','name':'Finans ve raporlama','tags':['finans','fatura','bütçe','maliyet','gelir'], 'tools':['research','document','writer','data','capability','verify']},
    {'id':'social','name':'Sosyal medya','tags':['sosyal medya','instagram','youtube','telegram','yorum'], 'tools':['account','research','writer','media','publish','data','monitor','capability','verify']},
    {'id':'store','name':'Mağaza ve müşteri işleri','tags':['mağaza','stok','sipariş','müşteri','satış'], 'tools':['research','document','account','writer','data','capability','verify']},
    {'id':'development','name':'Yazılım ve test','tags':['kod','python','javascript','yazılım','test'], 'tools':['coder','verify']},
    {'id':'production','name':'Belge ve medya üretimi','tags':['belge','rapor','video','görsel','ses'], 'tools':['document','writer','media','verify']},
    {'id':'operations','name':'Bilgisayar ve operasyon','tags':['bilgisayar','uygulama','ekran','kamera','sistem'], 'tools':['action','application','desktop','observe','sharing','system','diagnose','schedule','verify']},
]


def _path(owner):
    service_store.identity(owner)
    path = ROOT / (owner + '.json')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Ekip kaydı sembolik bağ olamaz.')
    return path


def capabilities():
    from modules import goal_tools
    catalog = goal_tools.catalog()
    tools = {**catalog['workers'], **catalog['local_tools']}
    return [{'id':key, 'description':value,
             'scope':'Mevcut adaptör; bağlantı ve izin çalıştırma sırasında denetlenir'}
            for key,value in tools.items()]


def _validate(members):
    allowed = {item['id'] for item in capabilities()}
    if not isinstance(members,list) or not 1 <= len(members) <= 40:
        raise ValueError('1–40 uzman tanımlanabilir.')
    seen = set()
    result = []
    for item in members:
        if not isinstance(item,dict) or not {'id','name','tags','tools'}.issubset(item) or set(item)-{'id','name','tags','tools','enabled'}:
            raise ValueError('Uzman alanları id, name, tags ve tools olmalı.')
        ident = item['id']
        if not isinstance(ident,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,39}',ident) or ident in seen:
            raise ValueError('Uzman kimliği geçersiz veya yineleniyor.')
        if not isinstance(item['name'],str) or not item['name'].strip() or len(item['name']) > 80:
            raise ValueError('Uzman adı 1–80 karakter olmalı.')
        tags, tools = item['tags'], item['tools']
        if not isinstance(tags,list) or len(tags)>20 or any(not isinstance(t,str) or not t.strip() or len(t)>60 for t in tags):
            raise ValueError('Uzman anahtar sözcükleri geçersiz.')
        if not isinstance(tools,list) or not tools or any(not isinstance(t,str) or t not in allowed for t in tools) or len(set(tools))!=len(tools):
            raise ValueError('Uzman yalnız kayıtlı araçları kullanabilir.')
        seen.add(ident)
        entry={'id':ident,'name':item['name'].strip(),'tags':[t.strip() for t in tags],'tools':list(tools)}
        if 'enabled' in item:
            if type(item['enabled']) is not bool:raise ValueError('Uzman etkinliği boolean olmalı.')
            entry['enabled']=item['enabled']
        result.append(entry)
    return result


def members(owner):
    path = _path(owner)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    if path.stat().st_size > 100_000:
        raise ValueError('Ekip kaydı fazla büyük.')
    return _validate(json.loads(path.read_text(encoding='utf-8')))


def revision(entries):
    return hashlib.sha256(json.dumps(entries,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def save_members(owner, entries, expected_revision=None):
    with _LOCK:
        path = _path(owner)
        if expected_revision is not None and revision(members(owner))!=expected_revision:
            raise ValueError('Uzman dizini başka işlemde değişmiş; yenileyip tekrar kaydet.')
        entries = _validate(entries)
        path.parent.mkdir(parents=True,exist_ok=True)
        release_guard.atomic(path,json.dumps(entries,ensure_ascii=False).encode('utf-8'))
    return entries


def assign(owner, tool, instruction='', preferred=None):
    """Choose a compatible specialist; the result is a label, not authorization."""
    entries = members(owner)
    candidates = [m for m in entries if m.get('enabled',True) and tool in m['tools']]
    if preferred is not None:
        match = next((m for m in candidates if m['id']==preferred),None)
        if match is None:
            raise ValueError('Seçilen uzman bu aracı kullanamaz.')
        return {'id':match['id'],'name':match['name']}
    if not candidates:
        return {'id':'jarvis','name':'Jarvis'}
    text = str(instruction).casefold()
    generic = {'araştır','kaynak','rapor','belge','kod','test','video','görsel','ses','ekran','uygulama','sistem','bilgisayar'}
    scores = [(sum(1 if tag.casefold() in generic else 3 for tag in m['tags'] if tag.casefold() in text),-i,m) for i,m in enumerate(candidates)]
    match = max(scores,key=lambda row:row[:2])[2]
    return {'id':match['id'],'name':match['name']}


def _public(text, limit=1000):
    return privacy.redact(str(text or ''),force=True)[:limit]


def _job(owner, job, kind):
    from modules import result_presentation,goal_executor
    if job.get('owner')!=owner:raise ValueError('Görev sahibi eşleşmiyor.')
    original=job
    checked=result_presentation.inspect_job(job,kind)
    job=checked['job']
    steps = job.get('steps' if kind=='goal' else 'tasks',[])
    outputs = job.get('outputs',{})
    result = []
    for step in steps[-96:]:
        output = outputs.get(step['id'],{})
        specialist = step.get('specialist')
        tool = step.get('tool',step.get('agent',''))
        # Older journals remain visible without being rewritten.
        if not isinstance(specialist,dict):
            specialist = {'id':'jarvis','name':'Jarvis · eski kayıt'}
        artifacts = []
        for item in output.get('files',[]) or []:
            if isinstance(item,dict) and item.get('file'):
                artifacts.append(Path(item['file']).name)
        if output.get('file'):
            artifacts.append(Path(output['file']).name)
        result.append({'id':step['id'],'tool':tool,'specialist':specialist,
                       'state':step.get('state','unknown'),'depends':step.get('depends',[]),
                       'text':_public(('Denenen kaynak: '+step.get('input',{}).get('url','')) if tool=='research' and step.get('state')=='running' else output.get('text',output.get('message','')),1200),
                       'artifacts':list(dict.fromkeys(artifacts)),
                       'has_receipt':step['id'] in checked['verified'],
                       'attempts':step.get('attempts',1)})
    from modules import goal_executor
    pending=outputs.get(job.get('waiting'),{}) if kind=='goal' else {}
    if kind=='task':
        pending=next((outputs.get(s['id'],{}) for s in steps if s.get('state')=='approval'),{})
    return {'id':job['id'],'kind':kind,'state':job.get('state','unknown'),
            'record_state':original.get('state','unknown'),
            'verification_status':'unverified' if checked['unverified'] else 'checked',
            'control':goal_executor.control_key(original),
            'approval':_public(pending.get('text',pending.get('message','')),4000) if job.get('state')=='approval' else '',
            'approval_id':pending.get('id','') if job.get('state')=='approval' else '',
            'request':_public(job.get('request',job.get('instruction','')),1500),
            'created':job.get('created',0),'steps':result,
            'question':_public(('Sonuç kanıtı doğrulanamadı; kayıtlı iş tekrar çalıştırılmadı. ' if checked['unverified'] else '')+
                (('Model planı bekleniyor · '+str(max(0,int(time.time()-job.get('phase_started',time.time()))))+' saniye · çağrı sınırı '+str(goal_executor.PLANNER_SECONDS)+' saniye') if job.get('phase')=='planning' and job.get('state')=='running' else job.get('question',job.get('blocker','')))),
            'goals':[{'text':_public(g.get('text')),'state':g.get('state')} for g in job.get('goals',[])]}


def snapshot(owner):
    """Bounded local journal reads only; never polls a model, account or device."""
    _path(owner)
    from modules import execution_record, goal_executor, task_agents, task_queue
    jobs, warnings = [], []
    goal_root = goal_executor.STORE/owner
    for kind,root,loader in (
        ('goal',goal_root,lambda owner,ident:execution_record.load(goal_root,owner,ident)),
        ('task',task_agents.STORE/owner,task_agents._load),
    ):
        if not root.exists():
            continue
        if any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('Görev klasörü sembolik bağ olamaz.')
        paths = sorted(root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        # A goal has an ExecutionRecord beside its legacy journal; list each job once.
        entries = {}
        for path in paths:
            ident = path.name[:-len(execution_record.SUFFIX)] if kind=='goal' and path.name.endswith(execution_record.SUFFIX) else path.stem
            if ident!='latest':entries.setdefault(ident,path)
        for ident,path in list(entries.items())[:25]:
            try:
                if path.is_symlink() or path.stat().st_size>16_000_000:
                    raise ValueError('Geçersiz görev kaydı.')
                job = loader(owner,ident)
                if job.get('id')!=ident or (kind=='goal' and job.get('owner')!=owner):
                    raise ValueError('Görev sahibi veya kimliği eşleşmiyor.')
                jobs.append(_job(owner,job,kind))
            except (OSError,ValueError,KeyError,TypeError):
                warnings.append('Bir görev kaydı okunamadı; diğer işler gösteriliyor.')
    jobs.sort(key=lambda item:item['created'],reverse=True)
    for job in jobs:
        engine = goal_executor if job['kind']=='goal' else task_agents
        with engine._LOCK:
            active = owner in engine._ACTIVE and engine._ACTIVE_JOBS.get(owner)==job['id']
        if not active:
            if job['state']=='running':job['state']='interrupted'
            for step in job['steps']:
                if step['state']=='running':
                    step['state']='cancelled' if job['state']=='cancelled' else 'interrupted'
            if job['state']=='interrupted':job['question']='Çalışan yürütücü yok; kayıtlı iş kesilmiş olabilir. Sonucu inceleyerek sürdür.'
    scheduled = [{**row,'instruction':_public(row.get('instruction'))} for row in task_queue.rows(owner)]
    from modules import specialist_contracts,source_watch,capability_hub
    directory=members(owner)
    return {'owner':owner,'now':time.time(),'members':directory,'revision':revision(directory),'capabilities':capabilities(),
            'specialist_contracts':specialist_contracts.describe(owner),
            'source_watches':source_watch.rows(owner),'source_events':source_watch.events(owner),
            'capability_candidates':capability_hub.rows(owner),
            'jobs':jobs,'queue':scheduled,'warnings':list(dict.fromkeys(warnings)),
            'limits':['Finans günlük kur/CSV, mağaza CSV ve mevcut sosyal hesap okumaları desteklenir; canlı banka/mağaza yazma bağlantısı yoktur.',
                      'Uzman tanımı bağlantı veya işlem izni sağlamaz.',
                      'Tamamlandı kaydı içerik doğruluğunu garanti etmez.',
                      'Düzenli işler yalnız Jarvis açıkken çalışır.']}
