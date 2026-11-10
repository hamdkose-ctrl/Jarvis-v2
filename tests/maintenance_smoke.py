"""Real module integration, with device and provider operations mocked."""
import sys
import threading
import time
import concurrent.futures
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_privacy_voice_and_pending
import types
from unittest.mock import MagicMock
if 'pyautogui' not in sys.modules:
    stub = types.ModuleType('pyautogui')
    stub.__getattr__ = lambda attr: MagicMock()
    sys.modules['pyautogui'] = stub
import main,web
with patch.object(main,'emit') as emitted:
    result=main._study_intent('çalışmaya başla')
    assert 'dersi hazırlıyorum' in result
    emitted.assert_called_once_with('study_start','')

home=main.pc_profile()
people={name:SimpleNamespace(name=name,slug=name.lower()) for name in ('Hamdi','Ebru')}
with patch.object(main,'profile',people['Hamdi']),patch.object(main,'match_user',side_effect=lambda name:name if name in people else None),patch.object(main,'_get_profile',side_effect=lambda name:people[name]):
    def request(name, action):
        with main.as_user(name):
            main._session().pending_confirm=action
            time.sleep(.02)
            assert main.profile.name==name
            return main._session().pending_confirm
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(request,'Hamdi','shutdown');b=pool.submit(request,'Ebru','message')
        assert a.result()=='shutdown' and b.result()=='message'
    assert main.profile.name=='Hamdi'
    assert main._sessions.for_owner('hamdi').pending_confirm=='shutdown'
    assert main._sessions.for_owner('ebru').pending_confirm=='message'

with patch.object(web.study,'add_async',return_value={'ok':True}) as add:
    assert web.bridge.study_add_path('example.txt')=={'ok':True}
    assert add.call_args.args[0] is web._p()

from modules import nxapi
document=Mock();document.is_file.return_value=True
with patch.object(nxapi,'allowed',return_value=document),patch.object(main.docs,'summarize',return_value='Belge özeti'):
    assert 'Belge özeti' in main._file_command('"example.txt" özetle')
    assert main._session().last_doc[0]=='Belge özeti'
print('Real integration: concurrent engine profiles, study page dispatch and document actions passed')

from modules.session_state import SessionStore
# These checks use fresh sessions, not the pending approvals from the concurrency fixture.
with patch.object(main, '_sessions', SessionStore()):
    # Production handle must discard a previous phone reply and honor engine controls first.
    main._session().speech_override = 'Eski telefon çevirisi'
    assert main.handle('tamam') == 'Tamam.'
    assert main._session().speech_override is None
    from modules import pc_guide
    with patch.object(main, '_close_jarvis', return_value='kapandı') as close, patch.object(pc_guide, 'handle', return_value='Rehber devam ediyor') as guide:
        assert main.handle("Jarvis'i kapat") == 'kapandı'
        close.assert_called_once()
        guide.assert_not_called()
    with patch.object(main, '_cur_source', 'telefon'), patch.object(main, '_close_jarvis') as close:
        assert 'bilgisayarından' in main.handle('Jarvis kapat')
        close.assert_not_called()
    print('Motor: önceki sesli kısa yanıt temizliği, rehberlikten bağımsız kapatma ve telefon kapatma sınırı geçti.')

    with patch('modules.command_manager.dispatch', return_value=None), patch.object(main, '_user_controls', return_value=None), patch.object(main, '_planner_command', return_value=None), patch.object(main, '_macro_run', return_value='kısayol çalıştı') as run, patch.object(main, '_extra_commands') as extra:
        assert main.handle('özel deneme komutu') == 'kısayol çalıştı'
        run.assert_called_once()
        extra.assert_not_called()
    print('Motor: ilk hızlı işleyici yanıtladığında diğer işleyiciler ve yan etkileri çalışmıyor.')

people = {name: SimpleNamespace(name=name, slug=name.lower()) for name in ('Hamdi', 'Ebru', 'Can')}
with patch.object(main, 'profile', people['Hamdi']), patch.object(main, '_guest', None), patch.object(main, '_home', None), patch.object(main, 'match_user', side_effect=lambda name: name if name in people else None), patch.object(main, '_get_profile', side_effect=lambda name: people[name]):
    with main.as_user('Ebru'):
        assert main.pc_profile() is people['Hamdi']
        with main.as_user('Can'):
            assert main.profile is people['Can']
            assert main.pc_profile() is people['Hamdi']
        assert main.profile is people['Ebru']
        try:
            with main.as_user('Hamdi'):
                assert main.pc_profile() is people['Hamdi']
                raise RuntimeError('nested callback failed')
        except RuntimeError:
            pass
        assert main.profile is people['Ebru']
        assert main.pc_profile() is people['Hamdi']
        assert main._llm.current_user() == 'ebru'
    assert main.profile is people['Hamdi']
    assert main._guest is None and main._home is None
    assert main._llm.current_user() == 'hamdi'
print('İç içe kullanıcı bağlamları: PC kimliği, konuk geri dönüşü ve hata sonrası model bağlamı korundu.')
