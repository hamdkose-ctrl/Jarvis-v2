"""Read-only PC/audio readiness; hardware success is never inferred from imports."""
from __future__ import annotations
import importlib.util
import json
import platform
from pathlib import Path
import shutil
import sys
import time
from modules.diagnostics import record_failure as _record_failure


def _installed(package):
    try: return importlib.util.find_spec(package) is not None
    except (ValueError,ImportError): return False


def check():
    checks=[]
    def add(name,state,detail): checks.append({'name':name,'state':state,'detail':detail})
    add('Python','ok' if sys.version_info>=(3,10) else 'failed',platform.python_version())
    add('Windows PC kontrolleri','available' if sys.platform=='win32' else 'unverified',platform.system()+'; pencere/tuş/kapatma fiziksel test edilmedi')
    for package,label in [('pyautogui','PC otomasyonu'),('sounddevice','Ses sürücüsü'),('playwright','Tarayıcı ajanı')]:
        add(label,'installed' if _installed(package) else 'missing',package)
    if _installed('sounddevice'):
        try:
            import sounddevice as sd
            devices=sd.query_devices()
            inputs=[d['name'] for d in devices if d.get('max_input_channels',0)>0]
            outputs=[d['name'] for d in devices if d.get('max_output_channels',0)>0]
            add('Mikrofon aygıtı','available' if inputs else 'missing',', '.join(inputs) or 'Giriş aygıtı bulunamadı')
            add('Hoparlör aygıtı','available' if outputs else 'missing',', '.join(outputs) or 'Çıkış aygıtı bulunamadı')
        except Exception:
            _record_failure('modules/system_doctor.py:check')
            add('Ses aygıtları','failed','Sürücü/PortAudio aygıt sorgusu başarısız')
    add('Canlı mikrofon, uyandırma, TTS','unverified','Aygıt listesi sesli konuşmayı doğrulamaz; gerçek PC üzerinde ses testi gerekli')
    add('Node JS testleri','available' if shutil.which('node') else 'missing','node')
    return {'created':time.time(),'checks':checks,'hardware_verified':False}


def render(report):
    rows=['| Kontrol | Durum | Sonuç |','|---|---|---|']
    for row in report['checks']: rows.append('| '+' | '.join(str(row[k]).replace('|','/').replace('\n',' ') for k in ('name','state','detail'))+' |')
    return '\n'.join(rows)


def save(owner):
    from modules import nxapi
    import re
    if not re.fullmatch(r'[\w-]{1,100}',owner or ''): raise ValueError('Kullanıcı geçersiz.')
    report=check();root=Path(nxapi.FILES_DIR)/'Jarvis Tanılama'/owner;root.mkdir(parents=True,exist_ok=True)
    path=root/'pc-ses-kontrol.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def handle(owner,command):
    if command.casefold().strip(' .!') in ('pc ses kontrolü','pc ses kontrolu','sistem tanılama','sistem kontrolü'):
        return render(save(owner))
    return None
