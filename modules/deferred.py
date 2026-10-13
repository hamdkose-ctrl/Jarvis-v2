"""UI notices and shutdown requests must not keep an exiting process alive."""
import threading

def start(seconds, callback, *, timer_factory=None):
    timer = (timer_factory or threading.Timer)(seconds, callback)
    timer.daemon = True
    timer.start()
    return timer
