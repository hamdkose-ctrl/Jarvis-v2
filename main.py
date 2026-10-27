"""JARVIS entry point and compatibility facade; no command/listening business logic.

python main.py [--text] [--mute] [--devices] [--phone]
"""
import sys as _sys
from types import ModuleType as _ModuleType
from threading import RLock as _RLock
if __name__ == '__main__':
    if '--devices' not in _sys.argv:
        import instance as _instance
        _instance.take_over()
    _sys.modules['main'] = _sys.modules[__name__]
_context_instance = None
_context_lock = _RLock()

def _context():
    global _context_instance
    with _context_lock:
        if _context_instance is None:
            from modules.engine_runtime import EngineContext
            from modules import engine_background, task_queue
            runtime = EngineContext()
            runtime._morning_brief = lambda: engine_background._scheduled_brief(runtime, startup_delay=True)
            task_queue.set_daily_notify(lambda: engine_background._scheduled_brief(runtime))
            _context_instance = runtime
        return _context_instance


def main(ui=None):
    return _context().main(ui)


class _EngineFacade(_ModuleType):
    """Keep web/phone integrations on the same authoritative context."""
    def __getattr__(self, name):
        if name == '_runtime':
            return _context()
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(_context(), name)

    def __setattr__(self, name, value):
        if name not in self.__dict__ and _context().is_exported(name):
            _context().set_public(name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in self.__dict__:
            super().__delattr__(name)
        else:
            delattr(_context(), name)


_sys.modules[__name__].__class__ = _EngineFacade

if __name__ == '__main__':
    if '--devices' in _sys.argv:
        _context().list_input_devices()
    else:
        main()