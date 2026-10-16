"""Bounded local FFmpeg/FFprobe smoke check; never installs or downloads."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from modules import requests_state


def check():
    requests_state.check()
    tools={name:shutil.which(name) for name in ('ffmpeg','ffprobe')}
    missing=[name for name,path in tools.items() if not path]
    if missing:return {'ok':False,'text':'Eksik video araçları: '+', '.join(missing)+'. Windows için scripts/video_kurulum.bat çalıştırılabilir; ardından Jarvis yeniden başlatılmalı.'}
    try:
        for name in tools:
            subprocess.run([tools[name],'-version'],capture_output=True,timeout=5,check=True)
            requests_state.check()
        with tempfile.TemporaryDirectory(prefix='jarvis-video-check-') as folder:
            output=Path(folder)/'test.mp4'
            subprocess.run([tools['ffmpeg'],'-nostdin','-v','error','-n','-f','lavfi','-i','color=c=black:s=64x64:r=10',
                            '-t','0.3','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(output)],
                           capture_output=True,timeout=15,check=True)
            requests_state.check()
            if not output.is_file() or output.stat().st_size==0:
                raise ValueError('Test videosu oluşmadı.')
            result=subprocess.run([tools['ffprobe'],'-v','error','-show_streams','-show_format','-of','json',str(output)],
                                  capture_output=True,text=True,timeout=5,check=True)
            data=json.loads(result.stdout)
            video=next((s for s in data.get('streams',[]) if s.get('codec_type')=='video'),{})
            duration=float(data.get('format',{}).get('duration',0))
            if (video.get('codec_name')!='h264' or video.get('width')!=64 or video.get('height')!=64
                    or not math.isfinite(duration) or not 0.1<=duration<=0.5):
                raise ValueError('Test videosu doğrulanamadı.')
    except (OSError,subprocess.SubprocessError,ValueError,TypeError):
        return {'ok':False,'text':'Video araçları bulundu ancak çalışma testi başarısız. FFmpeg/FFprobe ve libx264 desteğini kontrol edin; dosya yolları veya araç çıktısı gösterilmedi.'}
    requests_state.check()
    return {'ok':True,'text':'FFmpeg ve FFprobe çalışıyor; gerçek kısa H.264 video üretimi ve boyut/süre doğrulaması geçti. Geçici çıktı temizlendi. Ses üretimi ve hesap bağlantıları bu testte denenmedi.'}


if __name__=='__main__':
    result=check();print(result['text']);raise SystemExit(0 if result['ok'] else 1)
