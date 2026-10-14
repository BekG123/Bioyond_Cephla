"""Explicitly armed empty-gripper rehearsal through the existing Flask service.

Default is read-only preview. Never enables, starts Lua, changes limits, clears
faults, connects directly to the controller, or retries an uncertain command.
Use the physical E-stop for immediate stopping. A local STOP file cancels
between segments. This script is not a Haiku motion tool.
"""
import argparse
import json
import math
from pathlib import Path
import time
import urllib.request

from pick_and_hold.Calibration.fast_disk import check_path, ensure_arrival, wrap, GuardedService

ROOT=Path(__file__).resolve().parents[1]
AXES=('X','Y','Z','Rz')


def split_leg(start,end):
    yaw=wrap(end['Rz']-start['Rz'])
    distance=math.dist([start[k] for k in AXES[:3]],[end[k] for k in AXES[:3]])
    if abs(yaw)>.05 and distance>.1:raise ValueError('Combined translation/rotation is not allowed')
    if abs(yaw)>.05 and min(start['Z'],end['Z'])<300:raise ValueError('Rotation requires TCP Z >=300')
    count=max(1,math.ceil(math.hypot(end['X']-start['X'],end['Y']-start['Y'])/10),
              math.ceil(abs(end['Z']-start['Z'])/5),math.ceil(abs(yaw)/5))
    if distance<.01 and abs(yaw)<.01:return []
    return [{**{k:start[k]+(end[k]-start[k])*i/count for k in AXES[:3]},
             'Rz':start['Rz']+yaw*i/count} for i in range(1,count+1)]


class Rehearsal:
    def __init__(self,output):
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.started=time.time();self.moves=0;self.events=[]

    def record(self,event,**fields):
        row=dict(t=round(time.time()-self.started,3),event=event,**fields)
        self.events.append(row)
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')

    def request(self,path,body=None):
        req=urllib.request.Request('http://127.0.0.1:5002'+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=90) as response:return json.load(response)

    def state(self,ready=False):
        if (self.output/'STOP').exists():raise ValueError('Local stop requested')
        s=self.request('/state');r=s['robot']
        if not r.get('connected') or not r.get('ok'):raise ValueError('Controller not connected/healthy; no automatic reconnect')
        if s['sequence']['active']:raise ValueError('Another console sequence is active')
        if not s['envelope']['enabled']:raise ValueError('Workspace envelope must remain enabled')
        if r.get('errors'):raise ValueError('Controller reports errors: '+str(r['errors']))
        if ready and not (r.get('enabled') and r.get('control_mode',{}).get('mode')=='auto'
                and r.get('program_state',{}).get('state')=='running' and r.get('lua_app_initialized')):
            raise ValueError('Controller must already be auto/enabled/running/initialized')
        for k in AXES:
            if not math.isfinite(r['pose_mm'][k]):raise ValueError('Invalid measured pose')
        return s

    @staticmethod
    def envelope(s):return {k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in AXES[:3]}

    def torque(self):
        result=self.request('/gripper',{'action':'torque'});self.record('torque',result=result)
        GuardedService.checked(result)
        if not result.get('telemetry_live'):raise ValueError('Live joint torque report required')
        if result.get('e1_torque',-100)<=-100:raise ValueError('Unexpected holding torque during empty-gripper rehearsal')
        return result

    def run(self,recipe,execute=False):
        points=json.loads(Path(recipe).read_text())['points']
        params=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
        s=self.state(ready=execute);initial=s;pose=s['robot']['pose_mm'];q=s['robot']['joints']
        expected=dict(zip(AXES,points[0][1][:4]));ensure_arrival(pose,expected)
        planned=[]
        for phase,values,dwell in points:
            end=dict(zip(AXES,values[:4]));q=check_path(pose,end,q,params,self.envelope(s))
            segments=split_leg(pose,end)
            planned.append(dict(phase=phase,end=end,e1=values[4],segments=segments))
            pose=end
        self.record('preflight',initial=initial,phases=planned,execute=execute)
        print(json.dumps(dict(preflight='passed',phases=len(planned),segments=sum(len(p['segments']) for p in planned),execute=execute)),flush=True)
        if not execute:return dict(ok=True,preview=True)
        previous=initial['robot']['pose_mm'];last_e1=None
        for phase in planned:
            print('PHASE: '+phase['phase'],flush=True)
            self.record('phase',name=phase['phase'])
            live=self.state(True);ensure_arrival(live['robot']['pose_mm'],previous)
            self.torque()
            if phase['e1']!=last_e1:
                self.record('gripper_command',target=phase['e1'])
                result=self.request('/gripper',dict(action='move',e1=phase['e1'],speed=5))
                self.record('gripper_reply',result=result);GuardedService.checked(result)
                g=result.get('gripper',{})
                if abs(g.get('e1_position',-999)-phase['e1'])>.5 or g.get('e1_torque',-100)<=-100:
                    raise ValueError('Empty gripper did not reach the requested aperture')
                last_e1=phase['e1']
            for target in phase['segments']:
                live=self.state(True);actual=live['robot']['pose_mm'];ensure_arrival(actual,previous)
                expected_joints=check_path(actual,target,live['robot']['joints'],params,self.envelope(live))
                delta=wrap(target['Rz']-actual['Rz'])
                rotation=abs(delta)>.05
                if rotation:
                    if actual['Z']<300 or any(abs(actual[k]-target[k])>.1 for k in AXES[:3]):
                        raise ValueError('Rotation start is not stationary at clearance height')
                    body=dict(axis='Rz',delta=delta,speed=5);route='/jog'
                else:
                    body=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=actual['Rz'],
                              speed=10 if min(actual['Z'],target['Z'])>=300 else 5,interpolation='linear');route='/move'
                    target={**target,'Rz':actual['Rz']}
                self.record('motion_command',route=route,body=body,target=target)
                result=self.request(route,body);self.record('motion_reply',result=result)
                GuardedService.checked(result)
                after=self.state(True);ensure_arrival(after['robot']['pose_mm'],target)
                for k in ('J2','J3','J4'):
                    if abs(after['robot']['joints'][k]-expected_joints[k])>.5:
                        raise ValueError('Joint arrival differs from checked path: '+k)
                previous=after['robot']['pose_mm'];self.moves+=1
                self.record('arrival',pose=previous,joints=after['robot']['joints'])
                print(f"  {self.moves}: X{previous['X']:.3f} Y{previous['Y']:.3f} Z{previous['Z']:.3f} Rz{previous['Rz']:.3f}",flush=True)
            self.torque()
        return dict(ok=True,hardware_motion=True,empty_gripper=True,moves=self.moves,
                    final_state=self.state(True),elapsed_s=round(time.time()-self.started,3),haiku_execution=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe',required=True);p.add_argument('--output',required=True)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--operator-confirmed-empty-clear-verified',action='store_true')
    a=p.parse_args()
    if a.execute and not a.operator_confirmed_empty_clear_verified:p.error('Explicit current operator confirmation required')
    job=Rehearsal(a.output)
    try:result=job.run(a.recipe,a.execute)
    except Exception as ex:
        result=dict(ok=False,error=str(ex),moves=job.moves,no_automatic_retry=True)
        try:result['state_after_failure']=job.request('/state')
        except Exception as state_error:result['state_query_error']=str(state_error)
    (job.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)
    if not result['ok']:raise SystemExit(1)
