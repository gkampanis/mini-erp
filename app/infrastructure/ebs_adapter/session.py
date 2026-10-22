"""Win32 observation from the supplied batch baseline; no Tk or data imports."""
import ctypes
from ctypes import wintypes
import time
from app.infrastructure.ebs_adapter.adapter import WindowsAdapter


class WindowsSession(WindowsAdapter):
    def __init__(self):
        super().__init__()
        self.expected_ted=None
        u=ctypes.windll.user32
        u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];u.GetWindowTextW.restype=ctypes.c_int
        u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)];u.GetWindowThreadProcessId.restype=wintypes.DWORD
        u.EnumWindows.argtypes=[ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM),wintypes.LPARAM]


    def at_ebs(self,point):
        # Save/menu controls may be toolbar controls rather than WinForms edit fields.
        class Point(ctypes.Structure):_fields_=[('x',wintypes.LONG),('y',wintypes.LONG)]
        u=ctypes.windll.user32
        u.WindowFromPoint.argtypes=[Point];u.WindowFromPoint.restype=wintypes.HWND
        u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
        h=u.WindowFromPoint(Point(*point));root=u.GetAncestor(h,2)
        title=ctypes.create_unicode_buffer(512);u.GetWindowTextW(root,title,512)
        pid=wintypes.DWORD();u.GetWindowThreadProcessId(root,ctypes.byref(pid))
        if not h or not any(x in title.value.upper() for x in ('EBS','ENTERSOFT')):raise RuntimeError('Το σημείο δεν ανήκει στο Entersoft')
        if self.pid is None:self.pid=pid.value
        if self.pid!=pid.value:raise RuntimeError('Άλλαξε η διεργασία Entersoft')
        return root

    def health(self):
        if self.pid is not None:
            import ctypes
            # Query by observed window ownership, without opening/killing any process.
            windows=[];u=ctypes.windll.user32
            callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
            def collect(h,l):
                pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
                if pid.value==self.pid:windows.append(h)
                return True
            u.EnumWindows(callback(collect),0)
            if not windows:raise RuntimeError('Το Entersoft έκλεισε ή δεν βρίσκεται η αρχική διεργασία')
        if self._has_ebs_modal_dialog():raise RuntimeError('Υπάρχει διάλογος EBS. Έλεγξε το μήνυμα πριν συνέχεια.')

    def prepare(self,profile,expected=None):
        self.at_ebs(profile['save']);self.at_ebs(profile['new']);self.health()
        active=self._active_ted()
        if active is None:raise RuntimeError('Δεν προσδιορίστηκε το ενεργό ΤΕΔ. Άνοιξε κενό ΤΕΔ.')
        if expected is not None and active!=expected:raise RuntimeError('Δεν είναι ενεργό το νέο ΤΕΔ της ουράς')
        self.expected_ted=active
        return active

    def save(self,point):
        self.health()
        if self._active_ted()!=self.expected_ted:raise RuntimeError('Άλλαξε το ενεργό ΤΕΔ πριν το Save')
        self.at_ebs(point);self.pg.click(*point);time.sleep(1.3);self.health()

    def open_new(self,point):
        self.health();self.at_ebs(point);existing=self._mdi_forms()
        self.pg.click(*point);deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            self.health();fresh=self._mdi_forms()-existing
            if len(fresh)==1:self.expected_ted=next(iter(fresh));return self.expected_ted
            if len(fresh)>1:
                active=self._active_ted()
                if active in fresh:self.expected_ted=active;return active
                raise RuntimeError('Πολλές νέες φόρμες ΤΕΔ, χωρίς ασφαλή ενεργή φόρμα')
            time.sleep(.3)
        raise RuntimeError('Δεν αναγνωρίστηκε νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.')

    def _mdi_forms(self):
     """Enumerate candidate TED child windows (not necessarily only one)."""
     u=ctypes.windll.user32
     cbtype=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
     u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
     u.GetWindowTextW.restype=ctypes.c_int
     u.IsWindowVisible.argtypes=[wintypes.HWND];u.IsWindowVisible.restype=wintypes.BOOL
     def title(h):
      buf=ctypes.create_unicode_buffer(512);u.GetWindowTextW(h,buf,512);return buf.value.strip()
     results=[]
     def inner(h,l):
      s=title(h).upper()
      if u.IsWindowVisible(h) and (s.startswith('ΤΕΔ') or s.startswith('TED')):results.append(int(h))
      return True
     icb=cbtype(inner)
     u.EnumChildWindows.argtypes=[wintypes.HWND,cbtype,wintypes.LPARAM]
     def outer(h,l):
      t=title(h).upper()
      if 'EBS ERP' in t or 'ENTERSOFT' in t:u.EnumChildWindows(h,icb,0)
      return True
     ocb=cbtype(outer);u.EnumWindows.argtypes=[cbtype,wintypes.LPARAM];u.EnumWindows(ocb,0)
     # WinForms MDI may expose both an outer TED form and nested TED-labelled
     # controls. A nested descendant is NOT a second invoice window.
     candidates=set(results)
     u.GetParent.argtypes=[wintypes.HWND];u.GetParent.restype=wintypes.HWND
     canonical=set()
     for h in candidates:
      ancestor=u.GetParent(h)
      nested=False
      for _ in range(32):
       if not ancestor:break
       if int(ancestor) in candidates:
        nested=True;break
       ancestor=u.GetParent(ancestor)
      if not nested:canonical.add(h)
     return canonical

    def _active_ted(self):
     """Resolve the actually focused MDI child, never guess if there are multiple TEDs."""
     u=ctypes.windll.user32
     u.GetForegroundWindow.restype=wintypes.HWND
     u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
     u.GetWindowThreadProcessId.restype=wintypes.DWORD
     u.GetParent.argtypes=[wintypes.HWND];u.GetParent.restype=wintypes.HWND
     u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
     class GUITHREADINFO(ctypes.Structure):
      _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndActive',wintypes.HWND),('hwndFocus',wintypes.HWND),('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),('rcCaret',wintypes.RECT)]
     fg=u.GetForegroundWindow()
     if not fg:return None
     pid=wintypes.DWORD()
     tid=u.GetWindowThreadProcessId(fg,ctypes.byref(pid))
     info=GUITHREADINFO();info.cbSize=ctypes.sizeof(info)
     if not u.GetGUIThreadInfo(tid,ctypes.byref(info)):return None
     forms=self._mdi_forms()
     for root in (info.hwndFocus, info.hwndActive):
      h=root
      for _ in range(32):
       if not h:break
       if int(h) in forms:return int(h)
       h=u.GetParent(h)
     # An unambiguous single candidate is acceptable; ambiguity is not.
     return next(iter(forms)) if len(forms)==1 else None

    def _has_ebs_modal_dialog(self):
     # Detect standard Win32 popup dialogs owned by the Entersoft process.
     # Custom nonstandard dialogs still require explicit UI detection later.
     u=ctypes.windll.user32
     cbtype=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
     u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
     u.GetWindowThreadProcessId.restype=wintypes.DWORD
     u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
     u.IsWindowVisible.argtypes=[wintypes.HWND];u.IsWindowVisible.restype=wintypes.BOOL
     ebs_pids=set()
     def find_ebs(h,l):
      title=ctypes.create_unicode_buffer(512);u.GetWindowTextW(h,title,512)
      if 'EBS ERP' in title.value.upper() or 'ENTERSOFT' in title.value.upper():
       pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid));ebs_pids.add(pid.value)
      return True
     u.EnumWindows(cbtype(find_ebs),0)
     found=[]
     def find_dialog(h,l):
      if not u.IsWindowVisible(h):return True
      cls=ctypes.create_unicode_buffer(256);u.GetClassNameW(h,cls,256)
      if cls.value!='#32770':return True
      pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
      if pid.value in ebs_pids:found.append(h)
      return True
     u.EnumWindows(cbtype(find_dialog),0)
     return bool(found)
