"""Opt-in two-corner blending for the pinned successful six-point route."""
import math
from autonomy import TransferError
from cellvis24_recorded_hamilton_route import validate_shape,validate_speeds
from trajectory_queue import LuaTrajectory,KEYS,MOD

CAPABILITY=220112
ZONES=(-1,1,1,-1,-1,-1)
Z77_ZONES=(-1,1,-1,-1,-1,-1)
Z77_CAPABILITY=220113
ROUNDED_CAPABILITY=220114
ROUNDED_ZONES={'forward':(-1,1,1,5,-1,-1),'reverse':(-1,5,1,1,-1,-1)}


def require_capability(service,variant='blend3'):
    if variant not in ('blend3','opposite3'):raise TransferError('Unknown blend variant.')
    capability=ROUNDED_CAPABILITY if variant=='opposite3' else CAPABILITY
    reply=service.robot.set_sys_var_i({0:22,1:1,2:0,3:0,4:19 if variant=='opposite3' else 15,5:0,6:0},reply_timeout=10)
    if reply!={'index':1,'value':capability}:
        raise TransferError(f'Publish blended-transit queue{capability} first; no motion sent.')
    return dict(ok=True,blended_transit_capability=capability,motion_sent=False)


def validate(start,points,profile,speeds):
    if profile not in ('cellvis24_smoothed_forward','cellvis24_opposite_forward','cellvis24_opposite_reverse'):raise TransferError('Blending requires a pinned Hamilton transit.')
    r=validate_shape(start,points,profile);validate_speeds(start,points,profile,speeds)
    if len(points)!=6:raise TransferError('Expected six-point route for bounded blending.')
    return r


def blend_checksum(points,speeds,zones=ZONES):
    if len(points)!=len(speeds) or len(points)!=len(zones):raise TransferError('Incomplete blend packet')
    h=0
    for p,s,z in zip(points,speeds,zones):
        for v in [p[k] for k in KEYS]+[s,z]:h=(h*31+math.floor(v*100+.5))%MOD
    return h


class BlendedTransitTrajectory(LuaTrajectory):
    def execute(self,run,start,joints,points,cfg,speed,progress,**kwargs):
        if kwargs.pop('transit_blend',False) is not True:raise TransferError('Explicit transit blend selection required.')
        self.route=validate(start,points,kwargs.get('hamilton_short_side'),kwargs.get('segment_speeds'))
        profile=kwargs.get('hamilton_short_side')
        variant='opposite3' if profile.startswith('cellvis24_opposite_') else 'blend3'
        self.rounded=variant=='opposite3'
        self.zones=ROUNDED_ZONES[profile.rsplit('_',1)[1]] if self.rounded else ZONES
        if speed!=137 or kwargs.get('grouped'):raise TransferError('Blend candidate speed/geometry changed.')
        capability=require_capability(self.service,variant)['blended_transit_capability']
        result=super().execute(run,start,joints,points,cfg,speed,progress,**kwargs)
        return dict(result,zone=None,segment_zones=list(self.zones),blended_transit_capability=capability,
                    physical_continuity='requires_operator_observation')

    def check_motion_feedback(self,pose):
        if getattr(self,'rounded',False):
            # Native zone length does not certify the geometric turn onset.
            # Keep the existing 2mm/2deg corridor and add this trial constraint.
            yaw=pose['Rz']%360
            if yaw>246.0 and pose['Z']>82.15:
                raise TransferError('Rounded Hamilton final turn above Z82; stop, no retry.')

    def _job(self,op,token,values=None,offset=0,count=0,timeout=10):
        if op==8:op=20 if self.rounded else 16
        elif op==9:
            op=21 if self.rounded else 17;flat=[]
            for i in range(count):flat.extend([values[i*5+j] for j in range(5)]+[self.zones[offset+i]])
            values=dict(enumerate(flat))
        elif op==3:offset=blend_checksum(self.route['points'],self.route['segment_speeds'],self.zones)
        return super()._job(op,token,values,offset,count,timeout)
