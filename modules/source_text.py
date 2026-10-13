"""Bounded read-only source text cache; apply-time hashes always bypass this cache."""
from collections import OrderedDict
import threading

_LOCK=threading.Lock()
_CACHE=OrderedDict()
_MAX_BYTES=8*1024*1024

def read(path):
    try:before=path.stat()
    except FileNotFoundError:return None
    key=(str(path),before.st_ino,before.st_mtime_ns,before.st_size)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    data=path.read_bytes()
    text=data.decode('utf-8-sig')
    after=path.stat()
    if (after.st_ino,after.st_mtime_ns,after.st_size)!=(before.st_ino,before.st_mtime_ns,before.st_size):
        return text  # do not retain a snapshot changed during the read
    if len(data)<=_MAX_BYTES:
        with _LOCK:
            for old in list(_CACHE):
                if old[0]==str(path):del _CACHE[old]
            _CACHE[key]=text
            while len(_CACHE)>64 or sum(k[3] for k in _CACHE)>_MAX_BYTES:
                _CACHE.popitem(last=False)
    return text
