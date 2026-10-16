"""Jarvis brain: propose specialist-owned work, then execute only through the common orchestrator."""
from __future__ import annotations
import json
import re
from modules import goal_tools, llm, specialist_orchestrator, team_center


def _parse(text):
    if not isinstance(text,str):raise ValueError('Uzman planı metin olmalı.')
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
    try:value=json.loads(text)
    except ValueError:raise ValueError('Uzman planı geçerli JSON değil.') from None
    if not isinstance(value,dict) or set(value)!={'tasks'} or not isinstance(value['tasks'],list):
        raise ValueError('Uzman planı yalnız tasks listesi içermeli.')
    return value['tasks']


def plan(owner, request):
    members=team_center.members(owner)
    public=[{'id':m['id'],'name':m['name'],'tags':m['tags'],'tools':m['tools']} for m in members if m.get('enabled',True)]
    system='''Jarvis ana yürütme beynisin. Kullanıcının hedefini kayıtlı uzmanlara dağıt.
Yalnız JSON ver: {"tasks":[{"id":"kisa-id","specialist":"uzman-id","tool":"kayıtlı-araç","input":{},"depends":[]}]}.
1-16 adım. depends yalnız daha önceki adım kimlikleri olabilir. Uzmanın tools listesinde olmayan aracı verme.
Sayfa açmak, uygulama açmak veya kaynak dizini bulmak hedefin kendisi değilse son başarı sayılmaz; gerçek istenen sonucu üretecek adımları planla.
Kullanıcının vermediği hedef kişi, dosya yolu, hesap kimliği, URL veya izin uydurma. Kamuya açık kaynağı kullanıcıya geri sormak yerine research/data/browser gibi uygun okuma araçlarını kullan.
Dış gönderim/yayın/hesap/PC izinleri model tarafından verilmez; yürütme katmanı gerçek izin kapılarını uygular. Şifre veya anahtar isteme.
Bir uzman başarısız olabilir; mümkünse başka kayıtlı uzman/araçla güvenli alternatif adım planla. Doğrulanabilir teslim gerekiyorsa verify ekle.'''
    prompt='Hedef:\n'+request+'\n\nKayıtlı uzmanlar:\n'+json.dumps(public,ensure_ascii=False,separators=(',',':'))
    tasks=_parse(llm.ask(prompt,system=system,max_tokens=2200,validator=lambda raw:_parse(raw)))
    return specialist_orchestrator.validate(owner,request,tasks)


def _safe(tasks):
    """Only auto-enter the non-durable orchestrator when every planned effect is replay-safe."""
    return bool(tasks) and all(goal_tools.replay_safe(task['tool'],task['input']) for task in tasks)


def _render(result):
    if not isinstance(result,dict):return None
    lines=[]
    for task in result.get('tasks',[]):
        if task.get('state')=='done':
            lines.append('✓ '+str(task.get('specialist','uzman'))+' · '+str(task.get('tool','iş')))
            output=result.get('outputs',{}).get(task.get('id'),{})
            text=str(output.get('text') or output.get('message') or '').strip()
            if text:lines.append(text[:1200])
            if output.get('file'):lines.append('Dosya: '+str(output['file']))
            for item in output.get('files',[]):
                if isinstance(item,dict) and item.get('file'):lines.append('Dosya: '+str(item['file']))
    if result.get('state')=='done':
        return '\n\n'.join(lines) or 'Uzman ekip hedefi tamamladı.'
    return None


def try_run(runtime, request):
    """Return text when a safe specialist plan completed; otherwise let the durable goal loop own the task."""
    tasks=plan(runtime.profile.slug,request)
    if not _safe(tasks):return None
    result=specialist_orchestrator.run(runtime,request,tasks)
    return _render(result)


def run(runtime, request):
    tasks=plan(runtime.profile.slug,request)
    return specialist_orchestrator.run(runtime,request,tasks)


def catalog(owner):
    """Expose choices to the existing durable planner, without an extra model call."""
    return [{'id':m['id'],'name':m['name'],'tools':m['tools'],'tags':m['tags']}
            for m in team_center.members(owner) if m.get('enabled',True)]


def assign(owner,tool,request,preferred=None):
    return team_center.assign(owner,tool,request,preferred)
