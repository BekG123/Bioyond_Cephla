"""Session-local successful loading completion, separate from GUI button state."""
import math
import threading
import time
from uuid import uuid4

AXES=('x_mm','y_mm','z_mm')
LOADING_TOLERANCE=dict(x_mm=.02,y_mm=.02,z_mm=.05)


def near_loading(actual,target):
    return all(type(actual.get(k)) in (int,float) and math.isfinite(actual[k])
               and type(target.get(k)) in (int,float) and math.isfinite(target[k])
               and abs(actual[k]-target[k])<=LOADING_TOLERANCE[k] for k in AXES)


class LoadingState:
    def __init__(self):
        self.lock=threading.RLock();self.session_id=uuid4().hex
        self.status='unverified';self.receipt=None;self.reason='No successful loading completion in this session.'
    def invalidate(self,reason='Stage movement started.'):
        with self.lock:self.status='unverified';self.reason=reason;self.receipt=None
    def completed(self,success,actual,serial,reference_hash,error=None):
        with self.lock:
            self.status='completed' if success is True else 'failed'
            self.reason='' if success is True else str(error or 'Loading move failed.')
            self.receipt=(dict(id=uuid4().hex,session_id=self.session_id,completed_at=time.time(),
                position=dict(actual),controller_serial=serial,reference_hash=reference_hash) if success is True else None)
    def snapshot(self,actual,target,serial,reference_hash,busy=False):
        with self.lock:
            valid=(self.status=='completed' and self.receipt is not None
                   and serial is not None and self.receipt['controller_serial']==serial
                   and self.receipt['reference_hash']==reference_hash
                   and near_loading(actual,target) and near_loading(actual,self.receipt['position']))
            if self.status=='completed' and not valid:
                self.invalidate('Stage moved or loading reference/controller changed.')
            return dict(version=2,session_id=self.session_id,status=self.status,at_dropoff=valid and not busy,
                        receipt=self.receipt,reason=self.reason,position=dict(actual),tolerance_mm=LOADING_TOLERANCE)


def controller_identity(microscope,ports):
    """Identify the USB device actually opened by Squid, not a launch flag."""
    mcu=getattr(getattr(microscope,'low_level_drivers',None),'microcontroller',None)
    transport=getattr(mcu,'_serial',None)
    handle=getattr(transport,'_serial',None)
    port=getattr(handle,'port',None)
    if not port or getattr(handle,'is_open',False) is not True:return None
    matches=[p.serial_number for p in ports if str(p.device).casefold()==str(port).casefold() and p.serial_number]
    return str(matches[0]) if len(matches)==1 else None
