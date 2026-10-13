"""Explicit installer actions. No microphone capture, provider calls or settings edits."""
from __future__ import annotations
import argparse
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare_stt(data: Path):
    from faster_whisper import WhisperModel, download_model
    target = data / 'models' / 'stt' / 'small'
    required = ('config.json', 'tokenizer.json', 'model.bin')
    def complete(path):
        return all((path/f).is_file() and (path/f).stat().st_size for f in required)
    def validate(path):
        model = WhisperModel(str(path), device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        del model
    if complete(target):
        validate(target)
        print('Yerel ses: mevcut small modeli doğrulandı.', flush=True)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.stt-install-', dir=target.parent) as tmp:
        staged = Path(tmp) / 'small'
        print('Yerel Türkçe ses modeli indiriliyor (small)...', flush=True)
        download_model('small', output_dir=str(staged), use_auth_token=False)
        if not complete(staged):
            raise ValueError('Yerel model eksik indirildi; mevcut model korunuyor.')
        validate(staged)
        backup = target.with_name('small_backup_' + uuid.uuid4().hex)
        if target.exists():target.rename(backup)
        try:
            staged.rename(target)
        except BaseException:
            if backup.exists() and not target.exists():backup.rename(target)
            raise
    return target


def report(data: Path) -> dict:
    packages = {}
    for name in ('faster-whisper','markitdown','playwright','openwakeword','onnxruntime','google-genai'):
        try:packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name] = None
    plugins = []
    folder = data/'plugins'
    # Never import user plugins: top-level Python can perform arbitrary actions.
    for path in sorted(folder.glob('*.py')):
        item = {'file':path.name, 'imports':[]}
        try:
            if path.stat().st_size > 1024*1024:raise ValueError('dosya çok büyük')
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):names.update(a.name.split('.')[0] for a in node.names)
                elif isinstance(node,ast.ImportFrom) and node.module:names.add(node.module.split('.')[0])
            item['imports'] = sorted(names)
            item['has_handle'] = any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='handle' for n in tree.body)
        except (OSError,UnicodeError,SyntaxError,ValueError) as exc:item['error'] = type(exc).__name__
        plugins.append(item)
    result = {'packages':packages,'tools':{name:bool(shutil.which(name)) for name in ('git','node','ollama','claude','omniroute','headroom')},
              'plugins':plugins,'stt_small_ready':all((data/'models'/'stt'/'small'/f).is_file() for f in ('model.bin','tokenizer.json','config.json'))}
    data.mkdir(parents=True,exist_ok=True)
    dest=data/'kurulum_raporu.json'
    pending=dest.with_suffix('.tmp')
    pending.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(pending,dest)
    print('Kurulum/eklenti raporu:',dest,flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('models','report'))
    args=parser.parse_args()
    from config import DATA_DIR
    if args.action=='models':
        from modules.wakeword_models import ensure_models
        from openwakeword.model import Model
        ensure_models();Model(wakeword_models=['hey_jarvis'],inference_framework='onnx')
        prepare_stt(DATA_DIR)
    else:report(DATA_DIR)


if __name__=='__main__':main()
