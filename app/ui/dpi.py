"""Windows per-monitor DPI setup before creating Tk (Legend design reference)."""
import os

def enable():
    if os.name!='nt':return
    import ctypes
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):return
    except (AttributeError,OSError):pass
    try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError,OSError):pass
