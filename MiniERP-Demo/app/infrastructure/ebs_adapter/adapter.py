"""Field order/date technique adapted from the user-provided EBS v2.9 baseline.

The legacy source remains unchanged. This adapter deliberately never clicks Save.
"""
import csv
from datetime import datetime
from pathlib import Path
import sys
import time
import re

FIELDS=(('AFM_CREDITOR','vat'),('INVOICE_REFERENCE','invoice'),('INVOICE_DATE','date'),
        ('EXPENSE_ACCOUNT_GRID_CELL','account'),('NET_AMOUNT_GRID_CELL','net'))


def mapping_fields(mapping):
    base={field for field,_ in FIELDS};extra=set(mapping)-base;indexes=set()
    if not base.issubset(mapping):raise ValueError('Λείπουν πεδία mapper')
    for field in extra:
        match=re.fullmatch(r'(?:EXPENSE_ACCOUNT_GRID_CELL|NET_AMOUNT_GRID_CELL)_([0-9]+)',field)
        if not match or not 2<=int(match[1])<=100 or str(int(match[1]))!=match[1]:raise ValueError('Μη έγκυρο πεδίο πρόσθετης γραμμής EBS')
        indexes.add(int(match[1]))
    if indexes and indexes!=set(range(2,max(indexes)+1)):raise ValueError('Λείπει ενδιάμεση γραμμή mapping EBS')
    for index in indexes:
        if any(field+'_'+str(index) not in mapping for field in ('EXPENSE_ACCOUNT_GRID_CELL','NET_AMOUNT_GRID_CELL')):raise ValueError('Χρειάζονται λογαριασμός και καθαρή αξία για κάθε πρόσθετη γραμμή')
    return base|extra


def detail_positions(mapping,count):
    mapping_fields(mapping);rows=[]
    for index in range(1,count+1):
        suffix='' if index==1 else '_'+str(index)
        try:account=mapping['EXPENSE_ACCOUNT_GRID_CELL'+suffix];net=mapping['NET_AMOUNT_GRID_CELL'+suffix]
        except KeyError:raise ValueError('Κατέγραψε τη θέση λογαριασμού και καθαρής αξίας της γραμμής '+str(index)+' στις Ρυθμίσεις EBS') from None
        for point in (account,net):
            if not isinstance(point,(tuple,list)) or len(point)!=2 or any(type(v) is not int or abs(v)>65535 for v in point):raise ValueError('Μη έγκυρη θέση γραμμής EBS')
        if account==net or rows and (account[1]<=rows[-1][0][1] or net[1]<=rows[-1][1][1]):raise ValueError('Οι πρόσθετες θέσεις πρέπει να είναι στις επόμενες γραμμές EBS')
        rows.append((account,net))
    return rows


def load_mapper(path):
    path=Path(path)
    if path.stat().st_size>1024*1024:raise ValueError('Ο mapper υπερβαίνει το 1 MB')
    with path.open(encoding='utf-8-sig',newline='') as source:
        rows=list(csv.DictReader(source))
    data={}
    for row in rows:
        name=row.get('Field','')
        if name in data:raise ValueError('Διπλό πεδίο mapper: '+name)
        data[name]=row
    result={}
    for field,_ in FIELDS:
        if field not in data:raise ValueError('Λείπει πεδίο mapper: '+field)
        try:
            x,y=int(data[field]['MouseX']),int(data[field]['MouseY'])
            if field=='INVOICE_DATE':
                x=int(data[field]['RectX'])+5
                y=int(data[field]['RectY'])+max(3,int(data[field]['RectH'])//2)
            if not (-65535<=x<=65535 and -65535<=y<=65535):raise ValueError()
        except (KeyError,TypeError,ValueError):raise ValueError('Μη έγκυρες συντεταγμένες mapper: '+field) from None
        result[field]=(x,y)
    return result


def fill_sequence(driver,payload,mapping):
    """Pure orchestration testable with a fake driver; baseline keystroke order."""
    for field,key in FIELDS:
        x,y=driver.validate_target(field,mapping[field])
        driver.click(x,y);driver.sleep(.25)
        value=payload[key]
        if key=='date':
            driver.write(datetime.strptime(value,'%d/%m/%Y').strftime('%d%m%Y'),interval=.12)
            driver.press('tab');driver.sleep(.45)
            continue
        if key in ('account','net'):
            driver.press('f2');driver.sleep(.2)
        if key=='net':
            driver.ensure_net_focus(mapping[field],mapping['EXPENSE_ACCOUNT_GRID_CELL'])
        driver.hotkey('ctrl','a');driver.sleep(.15)
        if key=='net':driver.require_net_focus(mapping[field],mapping['EXPENSE_ACCOUNT_GRID_CELL'])
        driver.press('delete');driver.sleep(.15)
        if key=='net':driver.require_net_focus(mapping[field],mapping['EXPENSE_ACCOUNT_GRID_CELL'])
        driver.write(value,interval=.09)
        if hasattr(driver,'before_field_commit'):driver.before_field_commit(key,payload,(x,y))
        driver.press('tab');driver.sleep(.45)
        if hasattr(driver,'field_completed'):driver.field_completed(key,payload)


def fill_multiline_sequence(driver,payload,mapping):
    SimulationAdapter().fill(payload,mapping)
    lines=payload['detail_lines'];positions=detail_positions(mapping,len(lines))
    # Resolve and validate every target before any input, preserving the original
    # first-row sequence and its focus checks.
    for index,(account,net) in enumerate(positions,1):
        driver.validate_target('EXPENSE_ACCOUNT_GRID_CELL'+('' if index==1 else '_'+str(index)),account)
        driver.validate_target('NET_AMOUNT_GRID_CELL'+('' if index==1 else '_'+str(index)),net)
    fill_sequence(driver,dict(payload,account=lines[0]['account'],net=lines[0]['net']),mapping)
    for index,(line,(account,net)) in enumerate(zip(lines[1:],positions[1:]),1):
        previous_accounts=[p[0] for p in positions[:index]];previous_nets=[p[1] for p in positions[:index]]
        driver.validate_target('EXPENSE_ACCOUNT_GRID_CELL_'+str(index+1),account)
        driver.click(*account);driver.sleep(.25);driver.press('f2');driver.sleep(.2)
        driver.ensure_account_focus(account,net,previous_accounts)
        driver.hotkey('ctrl','a');driver.sleep(.15)
        driver.ensure_account_focus(account,net,previous_accounts)
        driver.press('delete');driver.sleep(.15)
        driver.ensure_account_focus(account,net,previous_accounts)
        driver.write(line['account'],interval=.09);driver.press('tab');driver.sleep(.45)
        driver.validate_target('NET_AMOUNT_GRID_CELL_'+str(index+1),net)
        driver.click(*net);driver.sleep(.25);driver.press('f2');driver.sleep(.2)
        driver.ensure_net_focus(net,account)
        def focused():
            driver.require_net_focus(net,account)
            for previous in previous_nets:driver.require_net_focus(net,previous)
        focused();driver.hotkey('ctrl','a');driver.sleep(.15);focused()
        driver.press('delete');driver.sleep(.15);focused()
        driver.write(line['net'],interval=.09);driver.press('tab');driver.sleep(.45)


class SimulationAdapter:
    def fill(self,payload,mapping):
        # Validate shape/date without touching the keyboard, mouse or EBS.
        datetime.strptime(payload['date'],'%d/%m/%Y')
        if any(not isinstance(payload.get(key),str) or not payload[key] or len(payload[key])>256 or any(ord(c)<32 or ord(c)==127 for c in payload[key]) for _,key in FIELDS):raise ValueError('Ελλιπή ή μη ασφαλή δεδομένα πληκτρολόγησης RPA')
        if 'detail_lines' in payload:
            from app.infrastructure.aade.lines import minor
            lines=payload['detail_lines']
            if not isinstance(lines,list) or not 2<=len(lines)<=100:raise ValueError('Μη έγκυρες γραμμές καταχώρισης')
            for line in lines:
                if not isinstance(line,dict) or any(not isinstance(line.get(k),str) or not line[k] or len(line[k])>256 or any(ord(c)<32 or ord(c)==127 for c in line[k]) for k in ('account','net')):raise ValueError('Μη ασφαλή δεδομένα γραμμής EBS')
                if type(line.get('net_minor')) is not int or type(line.get('tax_minor')) is not int or line['tax_minor']<0 or minor(line['net'].replace(',','.'))!=line['net_minor']:raise ValueError('Ασυμφωνία αξιών γραμμής EBS')
            if sum(l['net_minor'] for l in lines)!=minor(payload['net'].replace(',','.')):raise ValueError('Οι γραμμές δεν συμφωνούν με την καθαρή αξία παραστατικού')


class WindowsAdapter:
    def __init__(self):
        if sys.platform!='win32':raise RuntimeError('Η πραγματική συμπλήρωση EBS απαιτεί Windows')
        from app.infrastructure.optional_packages import activate
        activate()
        try:import pyautogui
        except ImportError:raise RuntimeError('Χρειάζεται ο προαιρετικός Windows RPA adapter (PyAutoGUI)') from None
        self.pg=pyautogui
        self.pg.FAILSAFE=True;self.pg.PAUSE=.15
        self.pid=None

    def _net_has_focus(self,point,account_point):
        """Observe the focused editor, not the shared HWND under a grid cell.

        A grid covering both mapped columns is deliberately insufficient proof.
        No captions, invoice values or UI automation packages are needed.
        """
        import ctypes
        from ctypes import wintypes
        class GUIInfo(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),
                      ('hwndActive',wintypes.HWND),('hwndFocus',wintypes.HWND),
                      ('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),
                      ('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),
                      ('rcCaret',wintypes.RECT)]
        u=ctypes.windll.user32
        for name,args,result in (
            ('GetForegroundWindow',[],wintypes.HWND),
            ('GetAncestor',[wintypes.HWND,wintypes.UINT],wintypes.HWND),
            ('GetWindowThreadProcessId',[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)],wintypes.DWORD),
            ('GetGUIThreadInfo',[wintypes.DWORD,ctypes.POINTER(GUIInfo)],wintypes.BOOL),
            ('GetWindowRect',[wintypes.HWND,ctypes.POINTER(wintypes.RECT)],wintypes.BOOL),
        ):
            function=getattr(u,name);function.argtypes=args;function.restype=result
        foreground=u.GetForegroundWindow()
        owner=wintypes.DWORD()
        if not foreground or not u.GetWindowThreadProcessId(foreground,ctypes.byref(owner)) or owner.value!=self.pid:return False
        # Query the mapped control's GUI thread; EBS can use several GUI threads.
        class Point(ctypes.Structure):_fields_=[('x',wintypes.LONG),('y',wintypes.LONG)]
        u.WindowFromPoint.argtypes=[Point];u.WindowFromPoint.restype=wintypes.HWND
        target=u.WindowFromPoint(Point(*point))
        target_owner=wintypes.DWORD()
        thread=u.GetWindowThreadProcessId(target,ctypes.byref(target_owner)) if target else 0
        if not thread or target_owner.value!=self.pid:return False
        info=GUIInfo();info.cbSize=ctypes.sizeof(info)
        if not u.GetGUIThreadInfo(thread,ctypes.byref(info)) or not info.hwndFocus:return False
        focused=info.hwndFocus
        editor_owner=wintypes.DWORD();u.GetWindowThreadProcessId(focused,ctypes.byref(editor_owner))
        if editor_owner.value!=self.pid or u.GetAncestor(focused,2)!=foreground:return False
        rect=wintypes.RECT()
        if not u.GetWindowRect(focused,ctypes.byref(rect)):return False
        def contains(p):return rect.left<=p[0]<rect.right and rect.top<=p[1]<rect.bottom
        return contains(point) and not contains(account_point)

    def require_net_focus(self,point,account_point):
        self.validate_target('NET_AMOUNT_GRID_CELL',point)
        if not self._net_has_focus(point,account_point):
            raise RuntimeError('Δεν επιβεβαιώθηκε η εστίαση στην καθαρή αξία. Δεν γράφτηκε αξία και δεν στάλθηκε Save.')

    def ensure_net_focus(self,point,account_point):
        # A click can merely dismiss the account lookup/editor. Retry activation
        # without clearing or typing until the actual net editor is observed.
        for attempt in range(3):
            self.validate_target('NET_AMOUNT_GRID_CELL',point)
            if self._net_has_focus(point,account_point):return
            if attempt<2:
                self.click(*point);self.sleep(.25)
                self.press('f2');self.sleep(.2)
        self.require_net_focus(point,account_point)

    def ensure_account_focus(self,point,net_point,previous_points):
        for attempt in range(3):
            self.validate_target('EXPENSE_ACCOUNT_GRID_CELL',point)
            if self._net_has_focus(point,net_point) and all(self._net_has_focus(point,p) for p in previous_points):return
            if attempt<2:self.click(*point);self.sleep(.25);self.press('f2');self.sleep(.2)
        raise RuntimeError('Δεν επιβεβαιώθηκε η επόμενη γραμμή λογαριασμού. Δεν στάλθηκε Save.')

    def validate_target(self,field,point):
        import ctypes
        from ctypes import wintypes
        class POINT(ctypes.Structure):_fields_=[('x',wintypes.LONG),('y',wintypes.LONG)]
        user=ctypes.windll.user32
        user.WindowFromPoint.argtypes=[POINT];user.WindowFromPoint.restype=wintypes.HWND
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
        user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        handle=user.WindowFromPoint(POINT(*point))
        cls=ctypes.create_unicode_buffer(256);user.GetClassNameW(handle,cls,256)
        root=user.GetAncestor(handle,2)
        title=ctypes.create_unicode_buffer(512);user.GetWindowTextW(root,title,512)
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(root,ctypes.byref(pid))
        if not handle or 'WindowsForms10.' not in cls.value or not any(x in title.value.upper() for x in ('EBS','ENTERSOFT')):
            raise RuntimeError('Δεν επαληθεύτηκε το EBS στο πεδίο '+field+'. Δεν στάλθηκε Save.')
        if self.pid is None:self.pid=pid.value
        if self.pid!=pid.value:raise RuntimeError('Άλλαξε η διεργασία EBS. Η συμπλήρωση διακόπηκε.')
        return point

    def fill(self,payload,mapping):
        if not mapping or any(field not in mapping for field,_ in FIELDS):raise ValueError('Απαιτείται πλήρης CSV mapper')
        SimulationAdapter().fill(payload,mapping)
        if payload.get('detail_lines'):fill_multiline_sequence(self,payload,mapping)
        else:fill_sequence(self,payload,mapping)

    def click(self,*point):self.pg.click(*point)
    def sleep(self,seconds):time.sleep(seconds)
    def write(self,value,interval):
        self.pg.failSafeCheck()
        if value.isascii():self.pg.write(value,interval=interval)
        else:
            type_unicode_exact(value,interval,self.pg.failSafeCheck)
    def press(self,key):self.pg.press(key)
    def hotkey(self,*keys):self.pg.hotkey(*keys)


def type_unicode_exact(text,interval=.075,check=lambda:None):
    """Adapt the supplied baseline SendInput helper; emit UTF-16 code units."""
    if sys.platform!='win32':raise RuntimeError('Η εισαγωγή Unicode απαιτεί Windows')
    import ctypes
    from ctypes import wintypes
    class Keyboard(ctypes.Structure):
        _fields_=[('vk',wintypes.WORD),('scan',wintypes.WORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
    class Mouse(ctypes.Structure):
        _fields_=[('x',wintypes.LONG),('y',wintypes.LONG),('data',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
    class Hardware(ctypes.Structure):
        _fields_=[('msg',wintypes.DWORD),('low',wintypes.WORD),('high',wintypes.WORD)]
    class Payload(ctypes.Union):_fields_=[('keyboard',Keyboard),('mouse',Mouse),('hardware',Hardware)]
    class Input(ctypes.Structure):_fields_=[('type',wintypes.DWORD),('payload',Payload)]
    send=ctypes.windll.user32.SendInput
    send.argtypes=[wintypes.UINT,ctypes.POINTER(Input),ctypes.c_int];send.restype=wintypes.UINT
    data=text.encode('utf-16-le')
    for offset in range(0,len(data),2):
        check();unit=int.from_bytes(data[offset:offset+2],'little')
        for flag in (0x0004,0x0006):
            event=Input(type=1,payload=Payload(keyboard=Keyboard(0,unit,flag,0,0)))
            if send(1,ctypes.byref(event),ctypes.sizeof(event))!=1:raise RuntimeError('Διακόπηκε η εισαγωγή Unicode στο EBS')
        time.sleep(interval)
