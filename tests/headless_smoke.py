"""Import and sequential conversation smoke test; OS/audio/provider adapters are mocked."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_privacy_voice_and_pending
if 'pyautogui' not in sys.modules:
    stub=types.ModuleType('pyautogui');stub.__getattr__=lambda attr:MagicMock();sys.modules['pyautogui']=stub
import main,web
from modules import pc_guide
with patch.object(pc_guide,'handle',return_value='Önce şu klasörü aç.') as coach:
    assert main.handle('PC yardımı: fotoğraf gönderme')=='Önce şu klasörü aç.'
    coach.assert_called_once()
with patch.object(pc_guide,'stop') as stop, patch.object(main.voice,'stop_speaking'), patch.object(main.requests_state,'cancel'):
    main.submit('dur','yazı',main.pc_profile().name)
    stop.assert_called_once()
text='The pump must be inspected tomorrow.'
main.emit('user',text)
main.emit('assistant','Kısa özet')
with patch.object(main.tr,'translate',return_value='Pompa yarın kontrol edilmeli.') as translate:
    result=main.handle('metni çevir');assert translate.call_args.args[0]==text
main.emit('assistant',result)
with patch.object(main,'ask',return_value='| İş | Zaman |\n|---|---|\n| Pompa kontrolü | Yarın |'):
    table=main.handle('bunu tabloya çevir')
assert main.last_doc[0]==table
main.emit('assistant',table)
assert main.handle('tamam')=='Tamam.'
web.bridge.chat_reset();assert main.last_doc is None
assert main.handle('çevir').startswith('Bu sohbette')
print('Headless: gerçek PC/WebUI içe aktarımı ve çevir→tablo→tamam→yeni sohbet akışı geçti (donanım/model taklitleri).')
