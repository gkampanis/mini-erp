"""Bounded, shareable EBS failure reports; no captions or business payloads."""
import ctypes
from ctypes import wintypes
from datetime import datetime,timezone
import json
from pathlib import Path
import platform
import struct
import sys
import threading
import traceback
import uuid
from app.infrastructure.ebs_adapter.adapter import FIELDS

_LOCK=threading.Lock()
MAX_REPORTS=20
SAFE_MESSAGES={
    'Δεν επαληθεύτηκε ο MDIClient του νέου ΤΕΔ.',
    'Δεν είναι ενεργό το νέο ΤΕΔ της ουράς',
    'Το προηγούμενο ΤΕΔ της ουράς δεν είναι πλέον διαθέσιμο.',
    'Δεν προσδιορίστηκε το ενεργό ΤΕΔ. Άνοιξε κενό ΤΕΔ.',
    'Άλλαξε το ενεργό ΤΕΔ πριν το Save',
    'Το νέο ΤΕΔ έκλεισε πριν την ενεργοποίηση.',
    'Το νέο ΤΕΔ δεν ανήκει στην ίδια διεργασία EBS.',
    'Το EBS δεν ανταποκρίθηκε στην ενεργοποίηση του νέου ΤΕΔ.',
    'Δεν αναγνωρίστηκε σταθερό νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.',
    'Δεν αναγνωρίστηκε νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.',
    'Πολλές νέες φόρμες ΤΕΔ, χωρίς ασφαλή ενεργή φόρμα',
    'Άλλαξε η διεργασία EBS. Η συμπλήρωση διακόπηκε.',
    'Άλλαξε η διεργασία Entersoft',
    'Το σημείο δεν ανήκει στο Entersoft',
    'Υπάρχει διάλογος EBS. Έλεγξε το μήνυμα πριν συνέχεια.',
    'Το Entersoft έκλεισε ή δεν βρίσκεται η αρχική διεργασία',
    'Διακόπηκε η εισαγωγή Unicode στο EBS',
}
for field,_ in FIELDS:
    SAFE_MESSAGES.add(f'Δεν επαληθεύτηκε το EBS στο πεδίο {field}. Δεν στάλθηκε Save.')
    SAFE_MESSAGES.add(f'Η θέση του πεδίου {field} δεν ανήκει στο ενεργό ΤΕΔ της ουράς. Έλεγξε το mapping πριν καταχώριση.')


def failure_hint(error):
    if type(error).__module__=='pyautogui' and type(error).__name__=='FailSafeException':
        return 'Ενεργοποιήθηκε η διακοπή ασφαλείας του ποντικιού σε γωνία της οθόνης. Έλεγξε το EBS πριν συνέχεια.'
    return ''


def native_snapshot(backend,profile):
    """Observe HWND/class/geometry only. Never activate, click, or read captions."""
    if sys.platform!='win32':return {'status':'NOT_AVAILABLE','reason':'non_windows'}
    u=ctypes.windll.user32
    for name,args,result in (
        ('GetForegroundWindow',[],wintypes.HWND),
        ('WindowFromPoint',[wintypes.POINT],wintypes.HWND),
        ('GetParent',[wintypes.HWND],wintypes.HWND),
        ('GetAncestor',[wintypes.HWND,wintypes.UINT],wintypes.HWND),
        ('GetWindow',[wintypes.HWND,wintypes.UINT],wintypes.HWND),
        ('GetWindowThreadProcessId',[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)],wintypes.DWORD),
        ('GetWindowRect',[wintypes.HWND,ctypes.POINTER(wintypes.RECT)],wintypes.BOOL),
        ('GetClassNameW',[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int],ctypes.c_int),
        ('IsWindowVisible',[wintypes.HWND],wintypes.BOOL),
    ):
        function=getattr(u,name);function.argtypes=args;function.restype=result
    nodes={}
    def window(handle):
        handle=int(handle or 0)
        if not handle or handle in nodes or len(nodes)>=96:return handle
        # No window text, account/VAT values, URLs or process command lines.
        name=ctypes.create_unicode_buffer(256);u.GetClassNameW(handle,name,256)
        pid=wintypes.DWORD();thread=u.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        rect=wintypes.RECT();has_rect=u.GetWindowRect(handle,ctypes.byref(rect))
        parent=int(u.GetParent(handle) or 0)
        node=dict(handle=handle,window_class=name.value,process_id=pid.value,thread_id=int(thread),parent=parent,
                  root=int(u.GetAncestor(handle,2) or 0),owner=int(u.GetWindow(handle,4) or 0),visible=bool(u.IsWindowVisible(handle)))
        if has_rect:node['rect']=[rect.left,rect.top,rect.right,rect.bottom]
        dpi=getattr(u,'GetDpiForWindow',None)
        if dpi is not None:
            dpi.argtypes=[wintypes.HWND];dpi.restype=wintypes.UINT
            node['dpi']=int(dpi(handle))
        nodes[handle]=node
        return handle
    def chain(handle):
        result=[]
        for _ in range(16):
            handle=window(handle)
            if not handle or handle in result or handle not in nodes:break
            result.append(handle);handle=nodes[handle]['parent']
        return result
    foreground=window(u.GetForegroundWindow())
    expected=window(getattr(backend,'expected_ted',None))
    candidates=[]
    try:candidates=sorted(int(h) for h in backend._mdi_forms())[:20]
    except Exception:pass
    for handle in candidates:chain(handle)
    points={}
    profile=profile or {}
    for field in [f for f,_ in FIELDS]+['save','new']:
        point=profile.get(field) if field in ('save','new') else profile.get('mapping',{}).get(field)
        if not isinstance(point,(list,tuple)) or len(point)!=2:continue
        point=[int(point[0]),int(point[1])]
        target=window(u.WindowFromPoint(wintypes.POINT(*point)))
        points[field]=dict(point=point,handle=target,parent_chain=chain(target))
    class GUI(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndActive',wintypes.HWND),('hwndFocus',wintypes.HWND),('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),('rcCaret',wintypes.RECT)]
    u.GetGUIThreadInfo.argtypes=[wintypes.DWORD,ctypes.POINTER(GUI)];u.GetGUIThreadInfo.restype=wintypes.BOOL
    focus=None
    if foreground and foreground in nodes:
        info=GUI();info.cbSize=ctypes.sizeof(info)
        if u.GetGUIThreadInfo(nodes[foreground]['thread_id'],ctypes.byref(info)):
            focus=dict(active=window(info.hwndActive),focused=window(info.hwndFocus),parent_chain=chain(info.hwndFocus))
    return dict(status='OBSERVED',foreground=foreground,expected_ted=expected,candidate_teds=candidates,focus=focus,points=points,windows=list(nodes.values()))


def write_report(erp,company,job,item_id,phase,error,backend=None,profile=None):
    """Best effort only: returning None must not alter or retry the posting."""
    try:
        from app import __version__
        row=erp.db.execute('SELECT i.id,i.document_id,i.status,j.status AS job_status,j.mode,j.execution,j.expected_ted,j.need_new FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.id=? AND i.id=?',(company,job,item_id)).fetchone()
        if row is None:return None
        state=dict(row)
        counts={r[0]:r[1] for r in erp.db.execute('SELECT status,count(*) FROM rpa_items WHERE job_id=? GROUP BY status',(job,))}
        saves={r[0] for r in erp.db.execute("SELECT action FROM audit_events WHERE company_id=? AND entity_id=? AND action IN ('rpa_save_pending','rpa_save_invoked') AND json_extract(payload,'$.job')=?",(company,row['document_id'],job))}
        root=Path(__file__).resolve().parents[3];frames=[]
        for frame in traceback.extract_tb(error.__traceback__)[-12:]:
            path=Path(frame.filename).resolve()
            if path.is_relative_to(root/'app'):
                frames.append(dict(module=path.relative_to(root).as_posix(),line=frame.lineno,function=frame.name))
        message=str(error)
        points={}
        profile=profile or {}
        for field in [f for f,_ in FIELDS]+['save','new']:
            point=profile.get(field) if field in ('save','new') else profile.get('mapping',{}).get(field)
            if isinstance(point,(list,tuple)) and len(point)==2 and all(isinstance(v,int) for v in point):points[field]=list(point)
        last_field=getattr(backend,'last_field',None)
        report=dict(schema=1,time=datetime.now(timezone.utc).isoformat(),app_version=__version__,python=platform.python_version(),system=platform.system(),pointer_bits=struct.calcsize('P')*8,
                    phase=phase if phase in ('preflight','prepare','new','claim','fill','save') else 'preflight',job_id=job,item_id=item_id,company_id=company,
                    exception=dict(type=type(error).__name__ if type(error).__module__=='builtins' or type(error).__name__=='TEDContextChanged' or (type(error).__module__=='pyautogui' and type(error).__name__ in ('FailSafeException','PyAutoGUIException')) else 'ExternalError',message=message if message in SAFE_MESSAGES else 'Non-allowlisted message omitted',frames=frames),
                    profile_points=points,last_field=last_field if last_field in {f for f,_ in FIELDS} else None,queue=state,queue_counts=counts,input_claimed=state['status']!='queued',save_pending_recorded='rpa_save_pending' in saves,save_returned_recorded='rpa_save_invoked' in saves,
                    save_may_have_been_sent=phase in ('save','new') and state['status']!='queued',ebs_storage_verified=False)
        if type(error).__module__=='pyautogui' and type(error).__name__=='FailSafeException':report['exception']['code']='pyautogui_failsafe'
        if isinstance(error,OSError) and isinstance(getattr(error,'winerror',None),int):report['exception']['winerror']=error.winerror
        try:report['native']=native_snapshot(backend,profile)
        except Exception:report['native']=dict(status='PARTIAL',reason='native_observation_failed')
        folder=Path(erp.directory)/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
        name='ebs-failure-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+uuid.uuid4().hex[:8]+'.json'
        path=folder/name
        with _LOCK:
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            for old in sorted(folder.glob('ebs-failure-*.json'),key=lambda p:p.name)[:-MAX_REPORTS]:old.unlink(missing_ok=True)
        return path
    except Exception:return None
