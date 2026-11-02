"""Real desktop/voice/Bridge paths, no live provider or physical OS effects."""
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import headless_smoke
import main,web
from modules import smart_router,task_agents,system_doctor,nxapi
from modules.system_control import ApplicationResult
from modules import desktop_agent, desktop_uia
from test_desktop_agent import FakeUI, action
# Uygulama açma: deterministik canonical kural gerçek sistem adaptörüne ulaşır (model sınıflandırıcısı yok).
with patch.object(main.system_control,'open_application',return_value=ApplicationResult('Paint açık',ok=True)) as launch:
    assert headless_smoke.canonical('paint aç','agents-open-app').ok
    launch.assert_called_once_with('paint')
# Çıplak deiktik Resolver hedef bağladığında ikinci bir "hangi hedef?" sorusuyla reddedilmez;
# cümlenin tamamı Goal Runner'a devredilir (kaldırılan sınıflandırıcının successor'ı tek kapıdır).
from modules import goal_executor
seen={}
main.emit('assistant','Paint üzerinde konuşuyoruz')
with patch.object(goal_executor,'run',side_effect=lambda runtime,command,**kw: seen.__setitem__('command',command) or 'Hedef yürütücüsüne devredildi'):
    reply=headless_smoke.canonical('onu aç','agents-deictic')
assert seen.get('command')=='onu aç' and 'devredildi' in reply
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    with patch.object(desktop_agent,'STORE',root/'desktop'), patch.object(desktop_uia,'DesktopUI',return_value=FakeUI()), patch.object(main._llm,'ask',side_effect=[__import__('json').dumps(action()),__import__('json').dumps({'op':'finish','expect':action()['expect'],'message':'19 doğrulandı'})]):
        answer=main.handle('PC görevi: Hesap Makinesi | 12 ile 7 topla')
        assert 'Tamamlandı' in answer and '19 doğrulandı' in answer
        assert desktop_agent._load(main.profile.slug)['status'] == 'done'
        assert desktop_agent._load(main.profile.slug)['history'][0]['verified']
        assert main._session().pending_desktop is None
    with patch.object(smart_router,'_STORE',root/'router'),patch.object(task_agents,'STORE',root/'tasks'),patch.object(nxapi,'FILES_DIR',root/'files'):
        response=main.handle('router durumu');assert '| Sağlayıcı |' in response
        assert main.handle('görev durumu')=='Henüz kayıtlı görev yok.'
        plan={'tasks':[{'id':'report','agent':'writer','input':{'instruction':'Yaz','filename':'test.md'}}]}
        with patch.object(main._llm,'ask',side_effect=[__import__('json').dumps(plan),'Rapor hazır']):
            answer=main.handle('görev: Test raporu hazırla');assert 'done' in answer
            job=task_agents.recent(main.profile.slug)
        response=main.handle('görev durumu');assert job['id'] in response and 'Rapor hazır' in response
        # Natural language reaches the real planner without a magic prefix: tek kapı Task zarfını verir.
        with patch.object(main._llm,'ask',side_effect=[__import__('json').dumps(plan),'Doğal komut raporu']):
            answer=headless_smoke.canonical('Test raporu oluştur ve kaydet','agents-nl-plan')
            assert 'Doğal komut raporu' in answer
            report=task_agents.recent(main.profile.slug)['outputs']['report']
            assert report['verified'] and Path(report['file']).read_text()=='Doğal komut raporu'
        voice_response=main._live_command('görev durumu');assert 'sohbet ekranında' in voice_response
        state=web.bridge.smart_router_status();assert 'capabilities' in state and 'key' not in str(state['capabilities'])
        with patch.object(system_doctor,'check',return_value={'checks':[{'name':'Mikrofon','state':'unverified','detail':'Fiziksel test gerekli'}],'hardware_verified':False}):
            assert 'unverified' in main.handle('pc ses kontrolü')
            assert web.bridge.system_doctor()['hardware_verified'] is False
print('Router/ajan PC+ses: gerçek Bridge, ana sohbet ve canlı ses yönlendirmesi, kalıcı rapor, doğrulanmamış donanım ayrımı geçti (model/OS taklitleri).')
