"""Exercise real Bridge and main dispatch with provider/OS adapters mocked."""
import inspect
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import headless_smoke  # Initializes audio/desktop test adapters and imports actual main/web.
import main,web
from modules import app_actions,personalization
p=main.profile
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
    with patch.object(main,'route',return_value=routed):
        reply=main.handle('Listeme bir iş ekle')
    assert not other.data['tasks']
    item=next(x for x in p.data['tasks'] if x['text']=='Sesli ortak işlem')
    assert web._p() is other  # Context restored after the voice operation.
finally:web._bridge_profile.reset(token)
with patch.object(main,'route',return_value={'intent':'app_action','args':{'action':'task_delete','params':{'tid':item['id']}}}):
    reply=main.handle('Listemdeki bu işi sil')
assert 'Onaylıyor' in reply
assert any(x['id']==item['id'] for x in p.data['tasks'])
main.handle('evet')
assert not any(x['id']==item['id'] for x in p.data['tasks'])
# A closed microphone is never re-enabled as a side effect of another action.
main.flags['mic']=False
with patch.object(main,'route',return_value={'intent':'app_action','args':{'action':'notes_list','params':{}}}):
    main.handle('Kayıtlı notlarımı listele')
assert main.flags['mic'] is False
with patch.object(web,'_set_mic') as mic:
    mic.side_effect=lambda value:main.flags.__setitem__('mic',value)
    main.flags['mic']=True
    assert 'kapatıldı' in main.handle('mikrofonu kapat')
    mic.assert_called_once_with(False)
# An actual theme change reaches settings storage.
with patch.object(main,'route',return_value={'intent':'app_action','args':{'action':'nx_set','params':{'key':'nx_theme','value':'light'}}}):
    main.handle('Temayı açık yap')
assert web.config.load_settings()['nx_theme']=='light'
# Router advertises exactly the callable catalog without needing an extra planning model call.
with patch.object(app_actions,'reference_context',return_value=''):
    with patch.object(main,'ask',return_value='{"intent":"app_action","args":{"action":"pc_windows","params":{}}}') as model:
        routed=main.route('Bilgisayardaki pencere listesini getir')
assert routed['intent']=='app_action'
assert model.call_count==1
assert 'pc_window' in model.call_args.args[1]
print(f'Sesli ortak işlemler: {len(app_actions.catalog())} kayıt, gerçek Bridge imzaları, kullanıcı ayrımı, silme/onay, mikrofon kapalı kalma ve tema kaydı geçti.')
