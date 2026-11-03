"""Exercise real Bridge and main dispatch with provider/OS adapters mocked."""
import inspect
import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import headless_smoke  # Initializes audio/desktop test adapters and imports actual main/web.
import main,web
from modules import app_actions,personalization
from modules import brain_entry, brain_core_map, brain_understanding, llm
from modules.brain_contracts import ActiveContext
p=main.profile
# Tek sınıflandırılmış-istek kapısının izdüşümü: turn bağlıyken kapıyı taklit eder, ikinci bir
# sınıflandırıcı değildir (kararı handoff üreten verir, yürütücü gerçek Bridge/app_actions'tır).
def door(command,rid,decision):
    with patch.object(brain_entry,'route_command',return_value=decision):
        return headless_smoke.canonical(command,rid)
def core(text,rid):
    semantic=brain_understanding.understand(owner=p.slug,request_id=rid,text=text,
        active_context=ActiveContext(owner=p.slug,request_id=rid),candidates=(),references=())
    return brain_core_map.core_plan(semantic.capability_hint,semantic.arguments)
# Every registered adapter has a compatible real API signature.
special={'tasks_list','notes_list','events_list','pc_windows','pc_window','pc_shortcut'}
for spec in app_actions._ACTIONS.values():
    if spec['action'] in special:continue
    fn=getattr(web.bridge,spec['target'])
    args={key:kind[1] if isinstance(kind,tuple) else None for key,kind in spec['params'].items()}
    inspect.signature(fn).bind(**args)
# Voice reaches the same actual storage API as the UI, even inside another Bridge profile context.
other=personalization.Profile('VoiceOther')
other.data['tasks']=[]
token=web._bridge_profile.set(other)
try:
    routed={'intent':'app_action','args':{'action':'task_add','params':{'text':'Sesli ortak işlem'}}}
    reply=door('Listeme bir iş ekle','voice-task-add',routed)
    assert not other.data['tasks']
    item=next(x for x in p.data['tasks'] if x['text']=='Sesli ortak işlem')
    assert web._p() is other  # Context restored after the voice operation.
finally:web._bridge_profile.reset(token)
reply=door('Listemdeki bu işi sil','voice-task-delete',
           {'intent':'app_action','args':{'action':'task_delete','params':{'tid':item['id']}}})
assert 'Onaylıyor' in reply
assert any(x['id']==item['id'] for x in p.data['tasks'])
main.handle('evet')
assert not any(x['id']==item['id'] for x in p.data['tasks'])
# A closed microphone is never re-enabled as a side effect of another action.
main.flags['mic']=False
door('Kayıtlı notlarımı listele','voice-notes-list',
     {'intent':'app_action','args':{'action':'notes_list','params':{}}})
assert main.flags['mic'] is False
with patch.object(web,'_set_mic') as mic:
    mic.side_effect=lambda value:main.flags.__setitem__('mic',value)
    main.flags['mic']=True
    # PR3A: mikrofon anahtarını seçen ham `mikrofon` dalı engine_commands'tan silindi.
    # Etki artık üretim zincirinin kendi sahibi: Fast gate `fast.mic.toggle` → tipli
    # `app_action(set_flag mic)` → gerçek Bridge `set_flag` → `_set_mic`.
    assert 'kapatıldı' in headless_smoke.canonical('mikrofonu kapat','voice-mic-toggle')
    mic.assert_called_once_with(False)
# An actual theme change reaches settings storage.
door('Temayı açık yap','voice-theme-set',
     {'intent':'app_action','args':{'action':'nx_set','params':{'key':'nx_theme','value':'light'}}})
assert web.config.load_settings()['nx_theme']=='light'
# Pencere listesi deterministik canonical plan: katalogdan çağrılabilir niyeti model çağırmadan üretir.
with patch.object(llm,'ask',Mock(side_effect=AssertionError('Model çağrısı gereksiz'))):
    plan=core('Açık pencereleri listele','voice-windows')
assert plan==('app_action',{'action':'pc_windows','params':{}})
print(f'Sesli ortak işlemler: {len(app_actions.catalog())} kayıt, gerçek Bridge imzaları, kullanıcı ayrımı, silme/onay, mikrofon kapalı kalma, tema kaydı ve modelsiz pencere planı geçti.')
