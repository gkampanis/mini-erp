"""Field order/date technique adapted from the user-provided EBS v2.9 baseline.

The legacy source remains unchanged. This adapter deliberately never clicks Save.
"""
import csv
from datetime import datetime
from pathlib import Path
import sys
import time

FIELDS=(('AFM_CREDITOR','vat'),('INVOICE_REFERENCE','invoice'),('INVOICE_DATE','date'),
        ('EXPENSE_ACCOUNT_GRID_CELL','account'),('NET_AMOUNT_GRID_CELL','net'))


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
        driver.hotkey('ctrl','a');driver.sleep(.15)
        driver.press('delete');driver.sleep(.15)
        driver.write(value,interval=.09)
        driver.press('tab');driver.sleep(.45)


class SimulationAdapter:
    def fill(self,payload,mapping):
        # Validate shape/date without touching the keyboard, mouse or EBS.
        datetime.strptime(payload['date'],'%d/%m/%Y')
        if any(not isinstance(payload.get(key),str) or not payload[key] or len(payload[key])>256 or any(ord(c)<32 or ord(c)==127 for c in payload[key]) for _,key in FIELDS):raise ValueError('Ελλιπή ή μη ασφαλή δεδομένα πληκτρολόγησης RPA')


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
        fill_sequence(self,payload,mapping)

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
