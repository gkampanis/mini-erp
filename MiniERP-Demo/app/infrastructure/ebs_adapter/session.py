"""Win32 observation from the supplied batch baseline; no Tk or data imports."""
import ctypes
from ctypes import wintypes
import time
from app.infrastructure.ebs_adapter.adapter import WindowsAdapter


class TEDContextChanged(RuntimeError):
    """The queued form is no longer current; no invoice input has started."""


class TEDActivationPending(RuntimeError):
    """An observed new form is temporarily busy; no second New is needed."""


class WindowsSession(WindowsAdapter):
    def __init__(self):
        super().__init__()
        self.expected_ted=None
        self._duplicate_context=None
        self._supplier_entered=False
        u=ctypes.windll.user32
        u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];u.GetWindowTextW.restype=ctypes.c_int
        u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)];u.GetWindowThreadProcessId.restype=wintypes.DWORD
        u.EnumWindows.argtypes=[ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM),wintypes.LPARAM]

    def _start_ebs(self):
        """Activate one verified EBS root once, before inspecting screen points."""
        if self.pid is not None:return
        u=ctypes.windll.user32
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        for name,args,result in (
            ('GetForegroundWindow',[],wintypes.HWND),
            ('GetWindow',[wintypes.HWND,wintypes.UINT],wintypes.HWND),
            ('GetWindowThreadProcessId',[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)],wintypes.DWORD),
            ('GetWindowTextW',[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int],ctypes.c_int),
            ('GetClassNameW',[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int],ctypes.c_int),
            ('IsWindowVisible',[wintypes.HWND],wintypes.BOOL),
            ('IsIconic',[wintypes.HWND],wintypes.BOOL),
            ('ShowWindow',[wintypes.HWND,ctypes.c_int],wintypes.BOOL),
            ('SetForegroundWindow',[wintypes.HWND],wintypes.BOOL),
        ):
            function=getattr(u,name);function.argtypes=args;function.restype=result
        windows={}
        def collect(handle,_):
            if not u.IsWindowVisible(handle) or u.GetWindow(handle,4):return True
            title=ctypes.create_unicode_buffer(512);u.GetWindowTextW(handle,title,512)
            cls=ctypes.create_unicode_buffer(256);u.GetClassNameW(handle,cls,256)
            if cls.value.startswith('WindowsForms10.') and any(s in title.value.upper() for s in ('EBS ERP','ENTERSOFT')):
                pid=wintypes.DWORD();u.GetWindowThreadProcessId(handle,ctypes.byref(pid))
                if pid.value:windows[int(handle)]=pid.value
            return True
        u.EnumWindows.argtypes=[callback,wintypes.LPARAM];u.EnumWindows(callback(collect),0)
        foreground=int(u.GetForegroundWindow() or 0)
        root=foreground if foreground in windows else next(iter(windows)) if len(windows)==1 else None
        if root is None:raise RuntimeError('Δεν βρέθηκε μοναδικό παράθυρο Entersoft για ενεργοποίηση.')
        if u.IsIconic(root):u.ShowWindow(root,9)
        if int(u.GetForegroundWindow() or 0)!=root:u.SetForegroundWindow(root)
        deadline=time.monotonic()+2
        while int(u.GetForegroundWindow() or 0)!=root:
            if time.monotonic()>=deadline:raise RuntimeError('Δεν ενεργοποιήθηκε το Entersoft στο προσκήνιο. Δεν στάλθηκε καταχώριση.')
            time.sleep(.05)
        self.pid=windows[root]


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
        self._check_duplicate()
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
        self._duplicate_context=None;self._supplier_entered=False
        self._start_ebs()
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
        self._check_duplicate()
        self.last_field=field
        point=super().validate_target(field,point)
        if self.expected_ted is None:return point  # Mapping capture, no typing.
        class Point(ctypes.Structure):_fields_=[('x',wintypes.LONG),('y',wintypes.LONG)]
        u=ctypes.windll.user32
        u.WindowFromPoint.argtypes=[Point];u.WindowFromPoint.restype=wintypes.HWND
        handle=u.WindowFromPoint(Point(*point))
        if self.expected_ted in self._ancestors(handle):return point
        raise RuntimeError('Η θέση του πεδίου '+field+' δεν ανήκει στο ενεργό ΤΕΔ της ουράς. Έλεγξε το mapping πριν καταχώριση.')

    def field_completed(self,key,payload):
        if key=='vat':
            editor=getattr(self,'_vat_editor',None)
            if editor:
                deadline=time.monotonic()+1.5
                while self._focused_ted_editor()==editor:
                    if time.monotonic()>=deadline:
                        from app.infrastructure.ebs_adapter.duplicates import CreditorResolutionRequired
                        self._supplier_entered=False;self._duplicate_context=None
                        raise CreditorResolutionRequired(vat=payload['vat'],invoice=payload['invoice'],expected_ted=self.expected_ted)
                    time.sleep(.1)
            self._supplier_entered=bool(self.expected_ted and self._active_ted()==self.expected_ted)
        elif key=='invoice' and self._supplier_entered:
            self._check_duplicate()

    def before_field_commit(self,key,payload,point=None):
        if key=='vat':
            self._supplier_entered=False;self._duplicate_context=None
            self._vat_editor=self._focused_ted_editor(point)
        if key=='invoice':
            self._duplicate_context=None
            if self._supplier_entered and self.expected_ted and self._active_ted()==self.expected_ted:
                self._duplicate_context=dict(vat=payload['vat'],invoice=payload['invoice'],expected_ted=self.expected_ted)

    def _focused_ted_editor(self,point=None):
        """Observe an actual edit child in the prepared same-process TED."""
        if not self.expected_ted or self._active_ted()!=self.expected_ted:return None
        u=ctypes.windll.user32
        class GUI(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndActive',wintypes.HWND),('hwndFocus',wintypes.HWND),('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),('rcCaret',wintypes.RECT)]
        u.GetGUIThreadInfo.argtypes=[wintypes.DWORD,ctypes.POINTER(GUI)];u.GetGUIThreadInfo.restype=wintypes.BOOL
        pid=wintypes.DWORD();thread=u.GetWindowThreadProcessId(self.expected_ted,ctypes.byref(pid))
        if not thread or pid.value!=self.pid:return None
        info=GUI();info.cbSize=ctypes.sizeof(info)
        if not u.GetGUIThreadInfo(thread,ctypes.byref(info)) or not info.hwndFocus:return None
        handle=info.hwndFocus;u.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        if pid.value!=self.pid or self.expected_ted not in self._ancestors(handle):return None
        cls=ctypes.create_unicode_buffer(256);u.GetClassNameW(handle,cls,256)
        if 'edit' not in cls.value.casefold():return None
        if point is not None:
            u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)];u.GetWindowRect.restype=wintypes.BOOL
            rect=wintypes.RECT()
            if not u.GetWindowRect(handle,ctypes.byref(rect)) or not (rect.left<=point[0]<rect.right and rect.top<=point[1]<rect.bottom):return None
        return int(handle)

    def _check_duplicate(self):
        from app.infrastructure.ebs_adapter.duplicates import parse_duplicate,DuplicateExistingDocument
        context=getattr(self,'_duplicate_context',None)
        if not context or not context['expected_ted'] or context['expected_ted']!=self.expected_ted:return
        dialogs=self._duplicate_dialogs()
        if len(dialogs)!=1:return
        dialog=dialogs[0]
        if dialog['pid']!=self.pid or dialog['owner_ted']!=self.expected_ted:return
        parsed=parse_duplicate(dialog['title'],dialog['body'])
        if parsed is None:return
        dismissed=self._dismiss_duplicate(dialog)
        self._duplicate_context=None
        raise DuplicateExistingDocument(**context,existing_reference=parsed[0],existing_date=parsed[1],existing_amount=parsed[2],dismissed=dismissed)

    def _duplicate_dialogs(self):
        """Read exact warning candidates, including custom WinForms dialogs."""
        from app.infrastructure.ebs_adapter.duplicates import is_ok_button,is_ok_label
        u=ctypes.windll.user32;cb=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        u.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT];u.GetWindow.restype=wintypes.HWND
        send=u.SendMessageTimeoutW
        send.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
        send.restype=ctypes.c_ssize_t
        def text(h):
            buf=ctypes.create_unicode_buffer(4096);result=ctypes.c_size_t()
            if not send(h,0x000D,len(buf),ctypes.addressof(buf),2,300,ctypes.byref(result)):return ''
            return buf.value
        dialogs=[]
        def observe(h,_):
            if not u.IsWindowVisible(h):return True
            pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
            if pid.value!=self.pid:return True
            caption=text(h)
            if ' '.join(caption.split())!='Προσοχή':return True
            u.IsWindowEnabled.argtypes=[wintypes.HWND];u.IsWindowEnabled.restype=wintypes.BOOL
            owner=u.GetWindow(h,4);chain=self._ancestors(owner)
            ted=self.expected_ted if self.expected_ted in chain else None
            if ted is None and owner and owner in self._ancestors(self.expected_ted) and self._active_ted()==self.expected_ted:ted=self.expected_ted
            parts=[];buttons=[]
            def child(c,_):
                name=ctypes.create_unicode_buffer(256);u.GetClassNameW(c,name,256);value=text(c)
                if is_ok_button(name.value,value):
                    if u.IsWindowVisible(c) and u.IsWindowEnabled(c):buttons.append(int(c))
                elif value.strip() and not is_ok_label(value):parts.append(value)
                return True
            u.EnumChildWindows.argtypes=[wintypes.HWND,cb,wintypes.LPARAM];u.EnumChildWindows(h,cb(child),0)
            dialogs.append(dict(handle=int(h),pid=pid.value,owner_ted=ted,title=caption,body=' '.join(parts),ok=buttons[0] if len(buttons)==1 else None))
            return True
        u.EnumWindows(cb(observe),0)
        return dialogs

    def _dismiss_duplicate(self,dialog):
        # Re-observe ownership, exact text and button immediately before activation.
        current=self._duplicate_dialogs()
        if len(current)!=1 or current[0]!=dialog or not dialog['ok']:return False
        u=ctypes.windll.user32;result=ctypes.c_size_t()
        if not u.SendMessageTimeoutW(dialog['ok'],0x00F5,0,0,2,500,ctypes.byref(result)):return False
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            if not any(d['handle']==dialog['handle'] for d in self._duplicate_dialogs()):return True
            time.sleep(.05)
        return False

    def _ancestors(self,handle):
        u=ctypes.windll.user32
        u.GetParent.argtypes=[wintypes.HWND];u.GetParent.restype=wintypes.HWND
        result=[]
        for _ in range(32):
            if not handle or int(handle) in result:break
            result.append(int(handle));handle=u.GetParent(handle)
        return result

    def _mdi_child(self,handle):
        # A TED caption can be on a nested pane, not the document HWND.
        u=ctypes.windll.user32
        u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        chain=self._ancestors(handle)
        for child,parent in zip(chain,chain[1:]):
            name=ctypes.create_unicode_buffer(256);u.GetClassNameW(parent,name,256)
            cls=name.value.casefold()
            if cls=='mdiclient' or cls.startswith('windowsforms10.mdiclient.'):return child,parent
        return None

    def _ted_for_window(self,handle,forms):
        for ancestor in self._ancestors(handle):
            if ancestor in forms:return ancestor
        return None

    def save(self,point):
        self.health()
        if self._active_ted()!=self.expected_ted:raise RuntimeError('Άλλαξε το ενεργό ΤΕΔ πριν το Save')
        self.at_ebs(point);self.pg.click(*point);time.sleep(1.3);self.health()

    def open_new(self,point):
        # A warning first observed during New cannot prove the previous fill.
        self._duplicate_context=None;self._supplier_entered=False
        self._start_ebs()
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
                    except TEDActivationPending:
                        self.health()
                        time.sleep(.15)
                        continue
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
        mdi=self._mdi_child(handle)
        # A custom tab host is not a native MDIClient. Let observed focus
        # establish readiness; never send MDI messages to an arbitrary parent.
        if mdi is None:return
        handle,parent=mdi
        send=u.SendMessageTimeoutW
        send.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
        send.restype=ctypes.c_ssize_t;result=ctypes.c_size_t()
        if not send(parent,0x0222,handle,0,0x0002,500,ctypes.byref(result)):
            raise TEDActivationPending('Το EBS δεν ανταποκρίθηκε στην ενεργοποίηση του νέου ΤΕΔ.')
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
      mdi=self._mdi_child(h)
      if mdi:
       canonical.add(mdi[0]);continue
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
     u.GetGUIThreadInfo.argtypes=[wintypes.DWORD,ctypes.POINTER(GUITHREADINFO)];u.GetGUIThreadInfo.restype=wintypes.BOOL
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
     threads={tid}
     for form in forms:
      owner=wintypes.DWORD();thread=u.GetWindowThreadProcessId(form,ctypes.byref(owner))
      if owner.value==pid.value:threads.add(thread)
     focused=set()
     for thread in threads:
      info=GUITHREADINFO();info.cbSize=ctypes.sizeof(info)
      if not u.GetGUIThreadInfo(thread,ctypes.byref(info)):continue
      for root in (info.hwndFocus,info.hwndActive):
       found=self._ted_for_window(root,forms)
       if found is not None:focused.add(found);break
     if focused:return next(iter(focused)) if len(focused)==1 else None
     return None

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
