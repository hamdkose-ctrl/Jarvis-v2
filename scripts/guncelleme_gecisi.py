"""One-time official suite migration for installers predating version-paired validation.

Downloads through the installed updater's authenticated GitHub connection. Keeps
all local-change, ancestry, candidate-test, transaction and safe-start gates.
No installed source/test file is overwritten before the normal apply transaction.
"""
import io
import re
import types
import zipfile
import updater
from modules import release_workspace


def main():
    if updater.REPO != 'hamdkose-ctrl/Jarvis-v2':
        raise ValueError('Bu geçiş yalnız Jarvis-v2 içindir.')
    info=updater.latest()
    if not info or not re.fullmatch(r'[a-fA-F0-9]{40}',str(info.get('sha',''))):
        raise ValueError('Resmî sürüm kimliği doğrulanamadı.')
    print('Resmî sürüm indiriliyor; kaynaklar henüz değiştirilmedi.',flush=True)
    raw=updater._get(f"https://api.github.com/repos/{updater.REPO}/zipball/{info['sha']}",timeout=60)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names=[n for n in archive.namelist() if n.split('/')[1:]==['modules','release_workspace.py']]
        if len(names)!=1:raise ValueError('Resmî doğrulama modülü bulunamadı.')
        source=archive.read(names[0])
    helper=types.ModuleType('jarvis_official_validation')
    exec(compile(source,'official-release-workspace.py','exec'),helper.__dict__)
    if not callable(getattr(helper,'official_release_validation',None)):
        raise ValueError('Bu resmî sürüm test geçişini desteklemiyor.')
    original=release_workspace.validate
    def validate(*args,**kwargs):
        with helper.official_release_validation():return helper.validate(*args,**kwargs)
    release_workspace.validate=validate
    try:
        print('Kurulu ve aday sürüm kendi testleriyle kontrol ediliyor; birkaç dakika sürebilir.',flush=True)
        print(updater.apply(info),flush=True)
    finally:release_workspace.validate=original


if __name__=='__main__':main()
