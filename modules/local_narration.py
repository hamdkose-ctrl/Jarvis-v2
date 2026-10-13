"""Optional offline narration: installed Piper model or Windows SAPI file stream."""
from pathlib import Path
import shutil
import subprocess
import sys
from modules import publish_services, service_store, requests_state
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
        try:
            if stream is not None:
                try:stream.Close()
                except Exception:
                    _record_failure('modules/local_narration.py:close')
                    raise Unavailable('Windows ses dosyası kapatılamadı; çıktı doğrulanmadı.') from None
        finally:
            if initialized:comtypes.CoUninitialize()


def check(owner):
    """Produce and validate a private temporary WAV without playing it."""
    import tempfile
    import wave
    service_store.identity(owner);requests_state.check()
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-narration-check-') as folder:
            path=Path(folder)/'check.wav'
            backend=render(owner,'Jarvis yerel ses kontrolü.',path)
            requests_state.check()
            if not path.is_file() or path.is_symlink() or path.stat().st_size>20_000_000:
                raise ValueError('Ses çıktısı geçersiz.')
            with wave.open(str(path),'rb') as audio:
                frames=audio.getnframes();rate=audio.getframerate()
                if audio.getcomptype()!='NONE' or audio.getnchannels() not in (1,2) or rate<=0 or not 0<frames/rate<=60:
                    raise ValueError('Ses metaverisi geçersiz.')
                data=audio.readframes(frames)
                silent=all(value==128 for value in data) if audio.getsampwidth()==1 else not any(data)
                if len(data)!=frames*audio.getnchannels()*audio.getsampwidth() or silent:
                    raise ValueError('Ses verisi eksik veya sessiz.')
    except (Unavailable,OSError,ValueError,EOFError,wave.Error,subprocess.SubprocessError):
        return {'ok':False,'text':'Yerel anlatım çalışma testi geçmedi. Kurulu Piper modeli veya Windows SAPI ve comtypes gerekli; bulut sesi kullanılmadı.'}
    requests_state.check()
    return {'ok':True,'text':'Yerel anlatım ('+backend+') gerçek WAV dosyası üretti; süre ve ses verisi doğrulandı. Geçici dosya temizlendi, hoparlörde çalınmadı. Ses dili ve kalitesi ayrıca denenmeli.'}
