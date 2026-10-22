"""Windows Credential Manager, scoped by local data directory/company/environment."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import sys

USER_HEADER = 'aade-user-id'
KEY_HEADER = 'ocp-apim-subscription-key'
OFFICIAL_DOCS = 'https://www.aade.gr/mydata/tehnikes-prodiagrafes-ekdoseis-mydata'


class VaultUnavailable(RuntimeError):
    pass


def target_for(directory, company_vat, environment):
    identity = str(directory.resolve())+'|'+str(company_vat)+'|'+environment
    return 'MiniERP/myDATA/'+hashlib.sha256(identity.encode()).hexdigest()


def validate(environment,username,key):
    if environment not in ('test','production'):
        raise ValueError('Επίλεξε δοκιμαστικό ή παραγωγικό περιβάλλον')
    if not isinstance(username,str) or not username.strip() or len(username)>256 or any(ord(c)<32 for c in username):
        raise ValueError('Δώσε έγκυρο όνομα χρήστη API')
    if not isinstance(key,str) or not key.strip() or len(key)>2048 or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in key.strip()):
        raise ValueError('Δώσε έγκυρο subscription key χωρίς κενά')
    return {'username':username.strip(),'key':key.strip()}


class WindowsCredentialStore:
    def _api(self):
        if sys.platform!='win32':
            raise VaultUnavailable('Η ασφαλής αποθήκευση χρησιμοποιεί το Windows Credential Manager. Δεν αποθηκεύτηκαν κωδικοί σε αρχείο ή βάση.')
        class Credential(ctypes.Structure):
            _fields_=[('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),
                      ('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),
                      ('CredentialBlobSize',wintypes.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),
                      ('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),
                      ('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]
        api=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
        api.CredWriteW.argtypes=[ctypes.POINTER(Credential),wintypes.DWORD];api.CredWriteW.restype=wintypes.BOOL
        api.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))];api.CredReadW.restype=wintypes.BOOL
        api.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD];api.CredDeleteW.restype=wintypes.BOOL
        api.CredFree.argtypes=[ctypes.c_void_p];api.CredFree.restype=None
        return api,Credential

    def read(self,target):
        api,Credential=self._api()
        pointer=ctypes.POINTER(Credential)()
        if not api.CredReadW(target,1,0,ctypes.byref(pointer)):
            code=ctypes.get_last_error()
            if code==1168:return None
            raise VaultUnavailable('Αποτυχία ανάγνωσης Windows Credential Manager (κωδικός %s)'%code)
        try:
            data=ctypes.string_at(pointer.contents.CredentialBlob,pointer.contents.CredentialBlobSize)
            value=json.loads(data.decode('utf8'))
            if not isinstance(value,dict) or set(value)!={'username','key'}:raise ValueError()
            return value
        except (ValueError,UnicodeError):
            raise VaultUnavailable('Η αποθηκευμένη εγγραφή κωδικών δεν είναι αναγνώσιμη') from None
        finally:api.CredFree(pointer)

    def write(self,target,value):
        api,Credential=self._api()
        data=json.dumps(value,ensure_ascii=False).encode('utf8')
        if len(data)>2400:raise ValueError('Το μέγεθος των κωδικών υπερβαίνει το ασφαλές όριο')
        blob=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
        record=Credential(Type=1,TargetName=target,CredentialBlobSize=len(data),CredentialBlob=blob,Persist=2,UserName='MiniERP')
        if not api.CredWriteW(ctypes.byref(record),0):
            raise VaultUnavailable('Αποτυχία αποθήκευσης Windows Credential Manager (κωδικός %s)'%ctypes.get_last_error())

    def delete(self,target):
        api,_=self._api()
        if not api.CredDeleteW(target,1,0) and ctypes.get_last_error()!=1168:
            raise VaultUnavailable('Δεν διαγράφηκε η εγγραφή από το Windows Credential Manager')
