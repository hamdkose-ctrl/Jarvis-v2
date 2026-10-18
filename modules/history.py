"""Per-user durable conversation history with bounded writes and reverse tail reads."""
from __future__ import annotations
import json
import os
import threading
import uuid
import tempfile
from pathlib import Path
from datetime import datetime
from config import DATA_DIR
from modules.turkish_text import lower

DIR = DATA_DIR / 'history'
_LOCK = threading.RLock()
_MAX_LINES = 5000
_MAX_BYTES = 24 * 1024 * 1024

def _path(slug):
    if not slug or any(c in str(slug) for c in ('/', '\\', '..')):
        raise ValueError('Geçersiz kullanıcı kimliği')
    DIR.mkdir(parents=True, exist_ok=True)
    return DIR / f'{slug}.jsonl'

def _reverse_lines(path):
    with path.open('rb') as f:
        f.seek(0,2)
        pos=f.tell(); pending=b''
        while pos:
            n=min(pos,65536);pos-=n;f.seek(pos)
            chunks=(f.read(n)+pending).split(b'\n');pending=chunks[0]
            for line in reversed(chunks[1:]):
                if line: yield line
        if pending: yield pending

def append(slug, role, text, source=''):
    text=(text or '').strip()
    if not text: return
    row={'id':uuid.uuid4().hex,'ts':datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'), 'role':role,'text':text,'source':source}
    try:
        with _LOCK:
            path=_path(slug)
            with path.open('a',encoding='utf-8') as f:
                f.write(json.dumps(row,ensure_ascii=False)+'\n')
            if path.stat().st_size > _MAX_BYTES: trim(slug)
    except OSError: pass
    return row

def read(slug, query='', limit=300):
    rows=[]; q=lower(query.strip())
    if limit <= 0: return rows
    try:
        with _LOCK:
            for line in _reverse_lines(_path(slug)):
                try: row=json.loads(line)
                except (ValueError,UnicodeError): continue
                if not isinstance(row,dict): continue
                if q and q not in lower(row.get('text','')): continue
                rows.append(row)
                if len(rows)>=limit: break
    except OSError: pass
    return rows[::-1]

def clear(slug):
    with _LOCK:
        try: _path(slug).unlink(missing_ok=True)
        except OSError: pass


def delete_day(slug, day, deleted_ids=None):
    """Remove exactly one displayed daily conversation, preserving other rows."""
    try:
        if datetime.strptime(day, '%Y-%m-%d').strftime('%Y-%m-%d') != day:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Geçersiz sohbet tarihi') from None
    with _LOCK:
        path = _path(slug)
        if not path.exists():
            return 0
        fd, temporary = tempfile.mkstemp(prefix='.history-delete-', dir=path.parent)
        removed = 0
        try:
            with os.fdopen(fd, 'wb') as output, path.open('rb') as source:
                for line in source:
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError):
                        row = None
                    if isinstance(row, dict) and str(row.get('ts', '')).startswith(day + ' '):
                        removed += 1
                        if deleted_ids is not None and row.get('id'):
                            deleted_ids.add(row['id'])
                    else:
                        output.write(line)
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return removed

def trim(slug):
    try:
        with _LOCK:
            path=_path(slug); lines=[]; size=0
            for line in _reverse_lines(path):
                if lines and (len(lines)>=_MAX_LINES or size+len(line)>_MAX_BYTES//2): break
                lines.append(line);size+=len(line)+1
            tmp=path.with_suffix('.tmp')
            tmp.write_bytes(b'\n'.join(reversed(lines))+b'\n');os.replace(tmp,path)
    except OSError: pass
