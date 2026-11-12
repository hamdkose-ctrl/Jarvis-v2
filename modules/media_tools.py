"""Local image/audio-to-video production with real FFmpeg/FFprobe evidence."""
import json
from pathlib import Path
import shutil
import subprocess
import uuid
from modules import requests_state, task_results, service_store, file_resource_guard, resource_leases


def validate(data):
    if isinstance(data,dict) and 'scenes' in data:
        from modules import media_studio
        return media_studio.validate(data)
    if not isinstance(data,dict) or set(data)-{'image','image_sha256','audio','audio_sha256','duration'}:
        raise ValueError('Video girdisi geçersiz.')
    for key in ('image','image_sha256'):
        if not isinstance(data.get(key),str) or not data[key]:raise ValueError('Görsel ve içerik özeti gerekli.')
    if ('audio' in data)!=('audio_sha256' in data):raise ValueError('Ses dosyasının özeti de gerekli.')
    duration=data.get('duration',10)
    if type(duration) not in (int,float) or not 1<=duration<=300:raise ValueError('Video süresi 1–300 saniye olmalı.')
    return dict(data)


def _source(path,digest,suffixes):
    from modules import nxapi
    path=Path(path);root=Path(nxapi.FILES_DIR).resolve()
    if path.is_symlink() or root not in path.resolve().parents or path.suffix.lower() not in suffixes:
        raise ValueError('Medya kaynağı Jarvis dosya alanında olmalı.')
    if task_results.file_digest(path)!=digest:raise ValueError('Medya kaynak dosyası değişmiş.')
    return path.resolve()


def prepare(data):
    if not isinstance(data,dict):raise ValueError('Video kaynağı JSON nesnesi olmalı.')
    if 'scenes' in data:
        from modules import media_studio
        return media_studio.prepare(data)
    from modules import nxapi
    data=dict(data);root=Path(nxapi.FILES_DIR).resolve()
    for key,suffixes in (('image',('.png','.jpg','.jpeg','.webp')),('audio',('.wav','.mp3','.ogg','.m4a'))):
        if key not in data:continue
        if not isinstance(data[key],str):raise ValueError('Medya dosya yolu geçersiz.')
        path=Path(data[key])
        if path.is_symlink() or root not in path.resolve().parents:raise ValueError('Kaynak Jarvis dosya alanında olmalı.')
        data.setdefault(key+'_sha256',task_results.file_digest(path))
        data[key]=str(_source(path,data[key+'_sha256'],suffixes))
    return validate(data)


def probe(path):
    tool=shutil.which('ffprobe')
    if not tool:raise ValueError('FFprobe bulunamadı; video doğrulanamaz.')
    result=subprocess.run([tool,'-v','error','-show_streams','-show_format','-of','json',str(path)],
                          capture_output=True,text=True,timeout=30,check=True)
    data=json.loads(result.stdout)
    video=next((s for s in data.get('streams',[]) if s.get('codec_type')=='video'),None)
    if not video or float(data.get('format',{}).get('duration',0))<=0:raise ValueError('Geçerli video akışı yok.')
    return {'width':video['width'],'height':video['height'],'duration':float(data['format']['duration']),
            'has_audio':any(s.get('codec_type')=='audio' for s in data['streams'])}


def run(owner,data):
    service_store.identity(owner)
    data=validate(data);requests_state.check()
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        return {'state':'unavailable','text':'Yerel video için FFmpeg ve FFprobe kurulmalı; ücretli servise geçilmedi.'}
    if 'scenes' in data:
        from modules import nxapi,media_studio
        output=Path(nxapi.FILES_DIR)/'Jarvis Görevler'/owner
        if output.is_symlink() or output.parent.is_symlink():raise ValueError('Medya çıktı klasörü sembolik bağ olamaz.')
        output.mkdir(parents=True,exist_ok=True)
        return media_studio.run(owner,data,ffmpeg,output)
    image=_source(data['image'],data['image_sha256'],('.png','.jpg','.jpeg','.webp'))
    audio=_source(data['audio'],data['audio_sha256'],('.wav','.mp3','.ogg','.m4a')) if 'audio' in data else None
    from modules import nxapi
    output=Path(nxapi.FILES_DIR)/'Jarvis Görevler'/owner
    if output.is_symlink() or output.parent.is_symlink():raise ValueError('Medya çıktı klasörü sembolik bağ olamaz.')
    output.mkdir(parents=True,exist_ok=True);path=output/(uuid.uuid4().hex[:12]+'-video.mp4')
    command=[ffmpeg,'-nostdin','-v','error','-n','-loop','1','-i',str(image)]
    if audio:command+=['-i',str(audio),'-af','apad']
    command+=['-t',str(data.get('duration',10)),'-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
              '-r','25','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p']
    if audio:command+=['-c:a','aac']
    command+=['-movflags','+faststart',str(path)]
    # Resource claim covers the entire FFmpeg write/verify window, not only
    # name selection. On crash the OS releases the claim; the incomplete
    # destination remains evidence for manual recovery, never a retry grant.
    with file_resource_guard.claim_paths(path):
        if path.exists() or path.is_symlink():
            raise resource_leases.LeaseConflict('Video target already exists.')
        try:
            subprocess.run(command,capture_output=True,timeout=180,check=True)
            requests_state.check();metadata=probe(path)
            if metadata['width']!=1280 or metadata['height']!=720 or abs(metadata['duration']-data.get('duration',10))>1 or bool(audio)!=metadata['has_audio']:
                raise ValueError('Video boyut/süre/ses kontrolünden geçmedi.')
            return {'state':'done','text':'Yerel görsel'+(' ve ses' if audio else '')+' kaynağından video üretildi.',
                    'file':str(path),'sha256':task_results.file_digest(path),'media':metadata}
        except BaseException:
            # Only the still-owned freshly-created path may be removed.
            path.unlink(missing_ok=True)
            raise
