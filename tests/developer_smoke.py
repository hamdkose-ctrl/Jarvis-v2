"""Real Bridge and engine integration; model, project and test subprocess faked."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import headless_smoke
import main, web
from modules import developer as dev, history

owner = main.profile.slug
svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect width="200" height="100" fill="blue"/></svg>'
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary); project = root / 'project'; project.mkdir()
    code = project / 'sample.py'; code.write_text('value = 1\n')
    with patch.object(dev, 'PROJECT', project), patch.object(dev, 'STORE', root / 'state'), patch.object(dev, '_AUTH', set()), patch.object(history, 'DIR', root / 'history'), patch.object(dev, '_test', return_value=(True, 'Candidate tests OK')), patch.object(dev.llm, 'ask') as ask:
        assert web.bridge.development_unlock('smoke-password')['ok']
        assert 'arayüz düğmesinden' in main.handle('geliştirme modunu aç')
        assert not web.bridge.development_status()['enabled']
        assert web.bridge.development_enable()['ok']
        ask.side_effect = [json.dumps(c) for c in (
            {'tool': 'read', 'path': 'sample.py'},
            {'tool': 'edit', 'path': 'sample.py', 'old': 'value = 1', 'new': 'value = 2'},
            {'tool': 'visual', 'title': 'Mavi taslak', 'svg': svg},
            {'tool': 'test'},
            {'tool': 'finish', 'message': 'Mavi tasarım ve kod taslağı.', 'memory': 'Mavi arayüz istendi.'})]
        answer = main.handle('Mavi tasarla, kodu da düzenle')
        assert '```diff' in answer and 'data:image/svg+xml;base64,' in answer
        assert code.read_text() == 'value = 1\n'
        main.emit('assistant', answer)
        assert web.bridge.history()[-1]['text'] == answer
        assert web.bridge.development_status()['draft_files'] == ['sample.py']
        # The real live voice wrapper returns a short spoken result, retaining full preview.
        voice_answer = main._live_command('son görseli göster')
        assert 'sohbet ekranında' in voice_answer
        assert 'data:image/svg+xml;base64,' in web.bridge.history()[-1]['text']
        with patch.object(dev, '_test', return_value=(True, 'Ran 1 test: OK')):
            assert 'uygulandı' in main.handle('değişiklikleri uygula')
        assert code.read_text() == 'value = 2\n'
        assert 'geri aldım' in main.handle('son geliştirmeyi geri al')
        assert code.read_text() == 'value = 1\n'
        main.handle('normal sohbete dön')
        assert not web.bridge.development_status()['unlocked']
        ask.assert_called()
print('Geliştirme gerçek Bridge: şifre, dosya okuma/düzenleme, kalıcı görsel, sesli kısa sonuç, uygulama ve geri alma geçti.')
