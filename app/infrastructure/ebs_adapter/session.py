"""Win32 observation from the supplied batch baseline; no Tk or data imports."""
import ctypes
from ctypes import wintypes
import time
from app.infrastructure.ebs_adapter.adapter import WindowsAdapter


class TEDContextChanged(RuntimeError):
    """The queued form is no longer current; no invoice input has started."""


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
        deadline=time.monotonic()+2
        while True:
            active=self._active_ted()
            if active is not None and (expected is None or active==expected):
                self.expected_ted=active
                for field,point in profile.get('mapping',{}).items():self.validate_target(field,point)
                return active
            if time.monotonic()>=deadline:break
            time.sleep(.1);self.health()
        if active is None:
            if expected is not None:raise TEDContextChanged('Το προηγούμενο ΤΕΔ της ουράς δεν είναι πλέον διαθέσιμο.')
            raise RuntimeError('Δεν προσδιορίστηκε το ενεργό ΤΕΔ. Άνοιξε κενό ΤΕΔ.')
        raise TEDContextChanged('Δεν είναι ενεργό το νέο ΤΕΔ της ουράς')

    def validate_target(self,field,point):
        point=super().validate_target(field,point)
        if self.expected_ted is None:return point  # Mapping capture, no typing.
        class Point(ctypes.Structure):_fields_=[('x',wintypes.LONG),('y',wintypes.LONG)]
        u=ctypes.windll.user32
        u.WindowFromPoint.argtypes=[Point];u.WindowFromPoint.restype=wintypes.HWND
        u.GetParent.argtypes=[wintypes.HWND];u.GetParent.restype=wintypes.HWND
        handle=u.WindowFromPoint(Point(*point))
        for _ in range(32):
            if not handle:break
            if handle==self.expected_ted:return point
            handle=u.GetParent(handle)
        raise RuntimeError('Η θέση του πεδίου '+field+' δεν ανήκει στο ενεργό ΤΕΔ της ουράς. Έλεγξε το mapping πριν καταχώριση.')

    def save(self,point):
        self.health()
        if self._active_ted()!=self.expected_ted:raise RuntimeError('Άλλαξε το ενεργό ΤΕΔ πριν το Save')
        self.at_ebs(point);self.pg.click(*point);time.sleep(1.3);self.health()

    def open_new(self,point):
        self.health();self.at_ebs(point);existing=self._mdi_forms()
        self.pg.click(*point);deadline=time.monotonic()+12
        stable=None;stable_since=None;fresh=set()
        while time.monotonic()<deadline:
            self.health();fresh=self._mdi_forms()-existing
            active=self._active_ted()
            candidate=next(iter(fresh)) if len(fresh)==1 else active if active in fresh else None
            if candidate is not None:
                if active!=candidate:
                    try:self._activate_fresh_ted(candidate)
                    except RuntimeError:
                        # Handle recreation during layout is transient. Other
                        # native errors are still surfaced, never swallowed.
                        if candidate in self._mdi_forms():raise
                # Activation/layout can recreate the HWND. Re-observe instead
                # of returning the handle captured before WM_MDIACTIVATE.
                fresh=self._mdi_forms()-existing;active=self._active_ted()
                if active in fresh:
                    if active!=stable:stable=active;stable_since=time.monotonic()
                    elif time.monotonic()-stable_since>=.6:
                        self.expected_ted=active;return active
                else:stable=None;stable_since=None
            else:stable=None;stable_since=None
            time.sleep(.15)
        if len(fresh)>1:raise RuntimeError('Πολλές νέες φόρμες ΤΕΔ, χωρίς ασφαλή ενεργή φόρμα')
        raise RuntimeError('Δεν αναγνωρίστηκε σταθερό νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.')

    def _activate_fresh_ted(self,handle):
        """Focus only the child just discovered by open_new, never a cached HWND."""
        self.health()
        if handle not in self._mdi_forms():raise RuntimeError('Το νέο ΤΕΔ έκλεισε πριν την ενεργοποίηση.')
        if self._active_ted()==handle:return
        u=ctypes.windll.user32
        u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        pid=wintypes.DWORD();u.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        if self.pid is None or pid.value!=self.pid:raise RuntimeError('Το νέο ΤΕΔ δεν ανήκει στην ίδια διεργασία EBS.')
        u.GetParent.argtypes=[wintypes.HWND];u.GetParent.restype=wintypes.HWND
        parent=u.GetParent(handle)
        u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        name=ctypes.create_unicode_buffer(256);u.GetClassNameW(parent,name,256)
        if not parent or 'mdiclient' not in name.value.casefold():raise RuntimeError('Δεν επαληθεύτηκε ο MDIClient του νέου ΤΕΔ.')
        send=u.SendMessageTimeoutW
        send.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
        send.restype=ctypes.c_ssize_t;result=ctypes.c_size_t()
        if not send(parent,0x0222,handle,0,0x0002,500,ctypes.byref(result)):
            raise RuntimeError('Το EBS δεν ανταποκρίθηκε στην ενεργοποίηση του νέου ΤΕΔ.')
        # prepare still verifies the resulting active HWND before any typing.

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
      if 'EBS ERP' in t or 'ENTERSOFT' in t:
       pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
       if self.pid is None or pid.value==self.pid:u.EnumChildWindows(h,icb,0)
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
     if self.pid is not None and pid.value!=self.pid:return None
     forms=self._mdi_forms()
     # EBS may host its MDI child on another GUI thread. Ask the verified
     # MDIClient for its active child; foreground-thread focus is insufficient.
     u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
     send=u.SendMessageTimeoutW
     send.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
     send.restype=ctypes.c_ssize_t
     active=set()
     for parent in {u.GetParent(form) for form in forms}:
      if not parent:continue
      name=ctypes.create_unicode_buffer(256);u.GetClassNameW(parent,name,256)
      if 'mdiclient' not in name.value.casefold():continue
      result=ctypes.c_size_t()
      if not send(parent,0x0229,0,0,0x0002,250,ctypes.byref(result)) or result.value not in forms:return None
      active.add(result.value)
     if active:return next(iter(active)) if len(active)==1 else None
     info=GUITHREADINFO();info.cbSize=ctypes.sizeof(info)
     if not u.GetGUIThreadInfo(tid,ctypes.byref(info)):return None
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
