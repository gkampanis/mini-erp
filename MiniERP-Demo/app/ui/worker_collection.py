"""Keep cyclic Tk finalization on the main thread while workers allocate.

Tk interpreters must not be destroyed by cyclic GC in a background thread:
https://bugs.python.org/issue39093
Reference counting remains enabled; automatic cyclic collection is suspended
only until the main-thread consumer receives every active worker result.
"""
import gc
import threading

_active=0
_restore=False


def begin():
    global _active,_restore
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Worker collection must be owned by the UI thread')
    if not _active:
        _restore=gc.isenabled()
        gc.disable()
        gc.collect()
    _active+=1


def end():
    global _active
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Worker collection must finish on the UI thread')
    if _active<=0:raise RuntimeError('No active worker collection')
    _active-=1
    if not _active:
        try:gc.collect()
        finally:
            if _restore:gc.enable()
