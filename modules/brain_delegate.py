"""Jarvis brain: propose specialist-owned work, then execute only through the common orchestrator."""
from __future__ import annotations
import json
import re
from modules import llm, specialist_orchestrator, team_center


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


def run(runtime, request):
    tasks=plan(runtime.profile.slug,request)
    return specialist_orchestrator.run(runtime,request,tasks)
