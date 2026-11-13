"""Opt-in direct rack candidate. Never replaces the accepted default route."""
import hashlib,json,math
from autonomy import TransferError
from scope_step_trial import near
from short_side_direct_transfer import validate_plan_route
from plan_cellvis24_direct_rack import OUTPUT,ACCEPTED
PROFILES=('cellvis24_direct_forward','cellvis24_direct_reverse')

def reference():
    from plan_cellvis24_direct_rack import build
    p=json.loads(OUTPUT.read_bytes());fresh=build()
    for key in ('parent_sha256','acceptance_sha256','config','global_envelope','station_envelope','routes'):
        if p[key]!=fresh[key]:raise TransferError('Direct candidate or evidence changed: '+key)
    return p

def validate_shape(start,points,profile):
    if profile not in PROFILES:raise TransferError('Unknown direct route.')
    r=reference()['routes'][profile.rsplit('_',1)[1]];near(start,r['start'],.05)
    if points!=r['points']:raise TransferError('Direct route differs from checked candidate.')
    return r

def validate_speeds(start,points,profile,speeds):
    if speeds!=validate_shape(start,points,profile)['segment_speeds']:raise TransferError('Direct contact/transit speeds changed.')

def validate_route(start,points,joints,cfg,envelope,profile):
    p=reference();r=validate_shape(start,points,profile)
    return validate_plan_route(p,r,start,points,joints,cfg,envelope)

from trajectory_queue import LuaTrajectory,KEYS,MOD

def mixed_checksum(points,speeds,kinds):
    h=0
    for p,s,k in zip(points,speeds,kinds):
        for v in [p[x] for x in KEYS]+[s,1 if k=='J' else 0]:h=(h*31+math.floor(v*100+.5))%MOD
    return h

class MixedWristTrajectory(LuaTrajectory):
    def execute(self,run,start,joints,points,cfg,speed,progress,**kwargs):
        profile=kwargs.get('hamilton_short_side')
        if profile not in PROFILES:raise TransferError('Mixed wrist executor only supports checked direct candidate.')
        self.route=validate_shape(start,points,profile)
        validate_speeds(start,points,profile,kwargs.get('segment_speeds'))
        reply=self.service.robot.set_sys_var_i({0:22,1:1,2:0,3:0,4:13,5:0,6:0},reply_timeout=10)
        if reply!={'index':1,'value':220111}:raise TransferError('Publish mixed-wrist queue220111 first; no motion sent.')
        result=super().execute(run,start,joints,points,cfg,speed,progress,**kwargs)
        return dict(result,segment_kinds=self.route['kinds'],mixed_wrist_capability=220111)

    def _job(self,op,token,values=None,offset=0,count=0,timeout=10):
        if op==8:op=12
        elif op==9:
            op=14;flat=[]
            for i in range(count):
                flat.extend([values[i*5+j] for j in range(5)]+[1 if self.route['kinds'][offset+i]=='J' else 0])
            values=dict(enumerate(flat))
        elif op==3:offset=mixed_checksum(self.route['points'],self.route['segment_speeds'],self.route['kinds'])
        return super()._job(op,token,values,offset,count,timeout)
