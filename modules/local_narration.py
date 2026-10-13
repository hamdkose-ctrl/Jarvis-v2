"""Optional offline narration: installed Piper model or Windows SAPI file stream."""
from pathlib import Path
import shutil
import subprocess
import sys
from modules import publish_services, service_store
_record_failure=publish_services._record_failure


class Unavailable(RuntimeError):pass


def render(owner,text,path):
    service_store.identity(owner)
    if not isinstance(text,str) or not text.strip() or len(text)>1800:raise ValueError('Yerel anlatım metni 1–1800 karakter olmalı.')
    try:config=publish_services.configuration(owner,'media_voice')
    except PermissionError:config={}
    backend=config.get('backend','auto')
    if backend not in ('auto','piper','sapi'):raise ValueError('Yerel anlatım motoru geçersiz.')
    piper=shutil.which('piper');model=Path(config.get('model',''))
    if backend in ('auto','piper') and piper and model.is_file() and not model.is_symlink() and model.suffix.lower()=='.onnx':
        subprocess.run([piper,'-m',str(model.resolve()),'-f',str(path)],input=text,text=True,capture_output=True,timeout=180,check=True)
        return 'piper'
    if backend=='piper' or sys.platform!='win32':raise Unavailable('Yerel anlatım için Piper modeli veya Windows SAPI gerekli; bulut sesine geçilmedi.')
    stream=None;initialized=False
    try:
        import comtypes
        from comtypes.client import CreateObject
        comtypes.CoInitialize();initialized=True
        stream=CreateObject('SAPI.SpFileStream');stream.Open(str(path),3,False)
        voice=CreateObject('SAPI.SpVoice');voice.AudioOutputStream=stream
        voice.Speak(text,16) # SPF_IS_NOT_XML: external text is never SSML/code.
        return 'sapi'
    except Exception:
        _record_failure('modules/local_narration.py:render')
        raise Unavailable('Windows yerel ses dosyası oluşturulamadı.') from None
    finally:
        if stream is not None:stream.Close()
        if initialized:comtypes.CoUninitialize()
