"""Bounded request-scoped response notification, without polling conversation history."""
from contextlib import contextmanager
import queue
import threading

class ResponseWaiters:
    def __init__(self):
        self._lock=threading.Lock()
        self._waiting={}

    @contextmanager
    def subscribe(self,owner,rid):
        key=(owner,rid)
        inbox=queue.Queue(maxsize=1)
        with self._lock:
            if key in self._waiting or len(self._waiting)>=128:
                raise ValueError('Telefon yanıt bekleme sınırına ulaşıldı.')
            self._waiting[key]=inbox
        try:yield inbox
        finally:
            with self._lock:self._waiting.pop(key,None)

    def publish(self,owner,rid,text):
        with self._lock:
            inbox=self._waiting.get((owner,rid))
            if inbox is not None:
                try:inbox.put_nowait(text)
                except queue.Full:pass
