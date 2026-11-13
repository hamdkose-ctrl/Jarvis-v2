"""Exercise real Bridge and main dispatch with provider/OS adapters mocked."""
import inspect
import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import headless_smoke  # Initializes audio/desktop test adapters and imports actual main/web.
import main,web
from modules import app_actions,personalization
from modules import brain_core_map, llm
p=main.profile
# Caller-supplied model decisions; actual Core validators and Bridge/domain workers.
def door(command, rid, capability, arguments):
    return headless_smoke.canonical(command, rid, capability, arguments)
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
    reply=door('Listeme Sesli ortak işlem ekle','voice-task-add','tasks.manage', {'operation':'add','text':'Sesli ortak işlem'})
    assert not other.data['tasks']
    item=next(x for x in p.data['tasks'] if x['text']=='Sesli ortak işlem')
    assert web._p() is other  # Context restored after the voice operation.
finally:web._bridge_profile.reset(token)
reply=door('Sesli ortak işlem görevini sil','voice-task-delete','tasks.manage', {'operation':'delete','text':'Sesli ortak işlem'})
assert 'Onaylıyor' in reply
assert any(x['id']==item['id'] for x in p.data['tasks'])
headless_smoke.canonical('evet','voice-task-approve')
assert not any(x['id']==item['id'] for x in p.data['tasks'])
# A closed microphone is never re-enabled as a side effect of another action.
main.flags['mic']=False
door('Kayıtlı notlarımı listele','voice-notes-list','notes.read', {'notes':{'which':'all'}})
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
door('Temayı açık yap','voice-theme-set','jarvis.selfctl', {'action':{'kind':'ui','key':'nx_theme','value':'light'}})
assert web.config.load_settings()['nx_theme']=='light'
# Pencere listesi deterministik canonical plan: katalogdan çağrılabilir niyeti model çağırmadan üretir.
with patch.object(llm,'ask',Mock(side_effect=AssertionError('Model çağrısı gereksiz'))):
    plan=brain_core_map.core_plan('desktop.windows.list', {'window':{'action':'list'}})
assert plan==('app_action',{'action':'pc_windows','params':{}})
print(f'Sesli ortak işlemler: {len(app_actions.catalog())} kayıt, gerçek Bridge imzaları, kullanıcı ayrımı, Core silme/onay, mikrofon kapalı kalma, tema kaydı ve tipli pencere planı geçti.')
