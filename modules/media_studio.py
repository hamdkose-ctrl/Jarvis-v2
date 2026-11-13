"""Offline storyboard montage, captions, optional audio/local narration."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from modules import media_tools,local_narration,requests_state,task_results,file_resource_guard,resource_leases

SIZES={'landscape':(1280,720),'portrait':(720,1280),'square':(1080,1080)}


def validate(data):
    if not isinstance(data,dict) or set(data)-{'scenes','audio','audio_sha256','layout','narration'}:raise ValueError('Stüdyo girdisi geçersiz.')
    scenes=data.get('scenes')
    if not isinstance(scenes,list) or not 1<=len(scenes)<=12:raise ValueError('1–12 sahne gerekli.')
    if data.get('layout','landscape') not in SIZES:raise ValueError('Video yönü geçersiz.')
    total=0
    for scene in scenes:
        if not isinstance(scene,dict) or set(scene)-{'image','image_sha256','caption','duration'}:raise ValueError('Sahne girdisi geçersiz.')
        if 'image' in scene:
            if not isinstance(scene['image'],str) or not isinstance(scene.get('image_sha256'),str) or not scene['image_sha256']:raise ValueError('Sahne görseli ve gerçek özeti gerekli.')
        elif not isinstance(scene.get('caption'),str) or not scene['caption'].strip():raise ValueError('Sahnede görsel veya metin gerekli.')
        if not isinstance(scene.get('caption',''),str) or len(scene.get('caption',''))>400:raise ValueError('Sahne yazısı en çok 400 karakter olmalı.')
        duration=scene.get('duration',5)
        if type(duration) not in (int,float) or not 1<=duration<=60:raise ValueError('Sahne süresi 1–60 saniye olmalı.')
        total+=duration
    if total>300:raise ValueError('Toplam video süresi 300 saniyeyi aşamaz.')
    if ('audio' in data)!=('audio_sha256' in data) or 'audio' in data and 'narration' in data:raise ValueError('Tek ses kaynağı kullanılmalı.')
    if 'narration' in data and (not isinstance(data['narration'],str) or not data['narration'].strip() or len(data['narration'])>1800):raise ValueError('Anlatım metni geçersiz.')
    return copy.deepcopy(data)


def prepare(data):
    data=copy.deepcopy(data)
    for scene in data.get('scenes',[]):
        if 'image' in scene:
            source=media_tools.prepare({'image':scene['image'],**({'image_sha256':scene['image_sha256']} if 'image_sha256' in scene else {})})
            scene.update(image=source['image'],image_sha256=source['image_sha256'])
    if 'audio' in data:
        from modules import nxapi
        path=Path(data['audio']) if isinstance(data['audio'],str) else None
        if path is None or path.is_symlink() or Path(nxapi.FILES_DIR).resolve() not in path.resolve().parents:raise ValueError('Ses kaynağı Jarvis dosya alanında olmalı.')
        source=media_tools._source(data['audio'],data.get('audio_sha256') or task_results.file_digest(data['audio']),('.wav','.mp3','.ogg','.m4a'))
        data.update(audio=str(source),audio_sha256=task_results.file_digest(source))
    return validate(data)


def _frame(scene,size,path):
    from PIL import Image,ImageDraw,ImageFont,ImageOps
    frame=Image.new('RGB',size,(12,19,30))
    if 'image' in scene:
        source=media_tools._source(scene['image'],scene['image_sha256'],('.png','.jpg','.jpeg','.webp'))
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=scene['image_sha256']:raise ValueError('Sahne görseli okuma sırasında değişti.')
        with Image.open(io.BytesIO(raw)) as image:
            image=ImageOps.contain(image.convert('RGB'),size)
            frame.paste(image,((size[0]-image.width)//2,(size[1]-image.height)//2))
    caption=scene.get('caption','')
    if caption:
        draw=ImageDraw.Draw(frame);font=None
        for name in ('DejaVuSans.ttf',str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'arial.ttf')):
            try:font=ImageFont.truetype(name,32);break
            except OSError:pass
        if font is None:font=ImageFont.load_default()
        lines=[];line=''
        for character in caption:
            candidate=line+character
            if character=='\n' or draw.textlength(candidate,font=font)>size[0]-80:
                lines.append(line);line='' if character=='\n' else character
            else:line=candidate
        lines.append(line);height=40*len(lines)+40;y=max(0,size[1]-height)
        draw.rectangle((0,y,size[0],size[1]),fill=(8,12,20))
        for line in lines:
            draw.text((40,y+15),line,font=font,fill='white');y+=40
    frame.save(path)


def run(owner,data,ffmpeg,output):
    data=validate(data);size=SIZES[data.get('layout','landscape')]
    total=sum(s.get('duration',5) for s in data['scenes'])
    final=output/(__import__('uuid').uuid4().hex[:12]+'-studio.mp4')
    with tempfile.TemporaryDirectory(prefix='studio-',dir=output) as folder:
        folder=Path(folder);audio=None;backend=None
        if 'audio' in data:audio=media_tools._source(data['audio'],data['audio_sha256'],('.wav','.mp3','.ogg','.m4a'))
        if 'narration' in data:
            audio=folder/'narration.wav'
            try:backend=local_narration.render(owner,data['narration'],audio)
            except local_narration.Unavailable as exc:return {'state':'unavailable','text':str(exc)}
            tool=__import__('shutil').which('ffprobe')
            result=subprocess.run([tool,'-v','error','-show_format','-of','json',str(audio)],capture_output=True,text=True,timeout=30,check=True)
            seconds=float(json.loads(result.stdout).get('format',{}).get('duration',0))
            if seconds<=0 or seconds>300:raise ValueError('Anlatım sesinin süresi geçersiz.')
            if seconds>total:
                ratio=seconds/total
                for scene in data['scenes']:scene['duration']=scene.get('duration',5)*ratio
                total=seconds
        concat=[]
        for index,scene in enumerate(data['scenes']):
            requests_state.check();image=folder/(str(index)+'.png');clip=folder/(str(index)+'.mp4')
            _frame(scene,size,image)
            subprocess.run([ffmpeg,'-nostdin','-v','error','-n','-loop','1','-i',str(image),'-t',str(scene.get('duration',5)),
                '-r','25','-c:v','libx264','-threads','2','-preset','veryfast','-pix_fmt','yuv420p',str(clip)],capture_output=True,timeout=180,check=True)
            concat.append("file '"+clip.name+"'")
        manifest=folder/'concat.txt';manifest.write_text('\n'.join(concat),encoding='utf-8')
        joined=folder/'joined.mp4'
        subprocess.run([ffmpeg,'-nostdin','-v','error','-n','-f','concat','-safe','1','-i',str(manifest),'-c','copy',str(joined)],capture_output=True,timeout=90,check=True)
        completed=joined
        if audio:
            completed=folder/'with-audio.mp4'
            subprocess.run([ffmpeg,'-nostdin','-v','error','-n','-i',str(joined),'-i',str(audio),'-map','0:v','-map','1:a','-af','apad',
                '-t',str(total),'-c:v','copy','-c:a','aac','-ar','48000','-b:a','128k','-movflags','+faststart',str(completed)],capture_output=True,timeout=180,check=True)
        requests_state.check();metadata=media_tools.probe(completed)
        if (metadata['width'],metadata['height'])!=size or abs(metadata['duration']-total)>1 or metadata['has_audio']!=bool(audio):raise ValueError('Stüdyo video kontrolü başarısız.')
        # No other Jarvis process may race this destination; exclusive create
        # and digest are inside the same OS-account physical file claim.
        with file_resource_guard.claim_paths(final):
            if final.exists() or final.is_symlink():
                raise resource_leases.LeaseConflict('Studio output already exists.')
            # A failed copy, fsync or digest must not leave a partial final
            # video that the next invocation could mistake for a completed
            # artifact. Keep cleanup under the exact same physical-file claim.
            created = False
            try:
                with completed.open('rb') as src, final.open('xb') as dst:
                    created = True
                    __import__('shutil').copyfileobj(src, dst)
                    dst.flush()
                    os.fsync(dst.fileno())
                digest = task_results.file_digest(final)
                return {'state':'done','text':'Sahne, yazı'+(' ve yerel ses' if audio else '')+' montajı üretildi.',
                        'file':str(final),'sha256':digest,'media':metadata,'studio':{'scenes':len(data['scenes']),'narration_backend':backend}}
            except BaseException:
                if created:
                    final.unlink(missing_ok=True)
                raise
