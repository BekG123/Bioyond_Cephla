"""Calibrate Cellvis once, then repeat the accepted station handling.

--execute confirms the same lid-off Cellvis plate is supported in HOME,
the jaws are empty/open28, both selected station holders and routes are clear,
Hamilton access is open when selected, the arm is released, hands are clear,
and the E-stop is supervised. --full-calibration visits IDLE once, restores
the holder and performs fresh Cellvis camera checks and pickup. No Lua startup,
fault recovery, imaging or pipetting. Calibration is outside the cycle loop.
"""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError


class ApiRejected(RuntimeError):
    """The host explicitly rejected the request, rather than losing its ACK."""


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stations',nargs='+',choices=['hamilton','squid'])
    p.add_argument('--full-calibration',action='store_true',help='Fresh Cellvis calibration once; visits IDLE first. Without station flags, stops at HOME clearance.')
    p.add_argument('--projected-calibration-trial',action='store_true',help='Use the shared projected-disk solution for alignment/descent; stop open before grip. Cannot combine with station handling.')
    p.add_argument('--home-to-hamilton-roundtrip',action='store_true')
    p.add_argument('--home-to-squid-roundtrip',action='store_true')
    p.add_argument('--cycles',type=int,default=1)
    p.add_argument('--source',type=Path,help='Fresh completed Cellvis HOME release/workflow receipt; defaults to newest.')
    p.add_argument('--execute',action='store_true')
    a=p.parse_args(argv)
    if a.projected_calibration_trial:a.full_calibration=True
    selected=[s for s,enabled in [('hamilton',a.home_to_hamilton_roundtrip),('squid',a.home_to_squid_roundtrip)] if enabled]
    if a.stations and selected:p.error('Use --stations or roundtrip flags, not both.')
    a.stations=a.stations or selected or ([] if a.full_calibration else ['hamilton','squid'])
    if a.full_calibration and a.source:p.error('Fresh calibration creates its own evidence; omit --source.')
    if not 1<=a.cycles<=100:p.error('--cycles must be1..100.')
    if not a.stations and a.cycles!=1:p.error('Calibration-only runs once; select stations to repeat handling.')
    if len(set(a.stations))!=len(a.stations):p.error('Choose each station once; use --cycles for repeats.')
    if a.projected_calibration_trial and a.stations:p.error('Projected calibration trial stops before grip; omit station flags.')
    return a


def api(path,body=None):
    q=Request('http://127.0.0.1:5002/'+path,data=None if body is None else json.dumps(body).encode(),
              headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
    try:
        with urlopen(q,timeout=30) as response:r=json.load(response)
    except HTTPError as error:
        raise ApiRejected(error.read().decode('utf-8',errors='replace')) from error
    if r.get('ok') is False:raise ApiRejected(str(r))
    return r


def prepare_calibration():
    """Use the existing checked IDLE and holder restore, never the48 button."""
    from cellvis24_squid_route import geometry
    from cellvis24_hamilton_route import reference
    from repeat_calibration_hamilton import return_idle
    from repeat_holder_calibration_20261110 import healthy,at_idle_pose
    from scope_step_trial import near
    from autonomy import TransferError
    import math
    s=api('state')
    if not s['robot'].get('connected'):
        api('connect',{'ip':'192.168.201.220'});s=api('state')
    r=healthy(s);e1=r['external_axes']['E1']
    if not math.isfinite(e1):raise RuntimeError('Fresh jaw feedback required.')
    if api('seq')['active']:raise RuntimeError('Another sequence is active.')
    ui=api('researcher/api/lacry/state')
    if ui['running']['active'] or ui.get('pending'):raise RuntimeError('Finish the current operation/plan first.')
    if not at_idle_pose(r['pose_mm']):
        short=dict(reference()['routes']['forward']['start']);short['Z']=round(short['Z']+25,2)
        matched=False
        for pose in (geometry()['clearance'],short):
            try:near(r['pose_mm'],pose,.05);matched=True
            except TransferError:pass
        if not matched or abs(e1-28)>.07:raise RuntimeError('Start at IDLE or accepted released Cellvis HOME clearance, jaws28.')
    return_idle()
    dispatched=False
    def send(path,body):
        nonlocal dispatched
        try:
            response=api(path,body)
        except ApiRejected:
            raise  # A rejected request never owns another operation.
        except BaseException:
            dispatched=True  # Lost acknowledgement: stop once, never resend.
            raise
        dispatched=True
        return response
    try:
        r=healthy(api('state'))
        if not at_idle_pose(r['pose_mm']):raise RuntimeError('IDLE not verified.')
        if abs(r['external_axes']['E1']-28)>.07:
            reply=send('gripper',dict(action='move',e1=28,speed=5))
            if reply.get('recovered'):raise RuntimeError('Jaw opening uncertain.')
            stable=0;deadline=time.monotonic()+3
            while stable<3:
                r=healthy(api('state'))
                if not at_idle_pose(r['pose_mm']):raise RuntimeError('Arm moved during jaw opening.')
                stable=stable+1 if abs(r['external_axes']['E1']-28)<=.07 else 0
                if time.monotonic()>deadline:raise TimeoutError('Opening did not settle.')
                time.sleep(.1)
            dispatched=False
        reply=send('developer/api/home-hamilton-exchange/restore-original',dict(ready=True,empty_gripper=True,holder_clear=True))
        if reply.get('started')!='home_hamilton_restore_original':raise RuntimeError('Unexpected holder dispatcher.')
        deadline=time.monotonic()+240;last=None
        while True:
            seq=api('seq');healthy(api('state'))
            if seq.get('name')!='home_hamilton_restore_original':raise RuntimeError('Holder task ownership changed.')
            message=(seq.get('log') or [{}])[-1].get('msg')
            if message!=last:print(message,flush=True);last=message
            if not seq['active']:
                if (seq.get('result') or {}).get('ok') is not True:raise RuntimeError('Holder restore failed; no calibration started.')
                dispatched=False;return
            if time.monotonic()>deadline:raise TimeoutError('Holder restore timed out; no retry.')
            time.sleep(.5)
    except BaseException:
        if dispatched:
            try:api('seq/stop',{})
            except Exception:pass
        raise


def main(argv=None):
    a=parse_args(argv)
    if not a.execute:
        from cellvis24_workflow import compile_steps,evidence
        steps=compile_steps(a.stations,a.cycles,a.full_calibration)
        if a.full_calibration:
            from cellvis24_calibration import compile_steps as calibration_steps,projected_trial_steps,reference
            reference();steps=(projected_trial_steps() if a.projected_calibration_trial else calibration_steps())+steps
        print(json.dumps(dict(motion_started=False,calibration_runs=int(a.full_calibration and not a.projected_calibration_trial),
            projected_trial=a.projected_calibration_trial,measured_target_pending=a.projected_calibration_trial,
            expected_outcome='Open jaws; inspect before grip' if a.projected_calibration_trial else 'Accepted workflow',
            preparation='Visit IDLE; open empty jaws28; restore holder1.77' if a.full_calibration else 'Fresh calibrated Cellvis HOME receipt',
            requires='Cellvis plate supported in HOME; empty jaws; unchanged fixtures and clear routes',
            stations=a.stations,cycles=a.cycles,acceptance_sha256=evidence(),
            steps=[{k:s[k] for k in ('cycle','station','kind','label')} for s in steps]),indent=2))
        return
    if a.full_calibration:prepare_calibration()
    body=dict(stations=a.stations,cycles=a.cycles,source=str(a.source.resolve()) if a.source else None,full_calibration=a.full_calibration,projected_trial=a.projected_calibration_trial)
    plan=api('developer/api/cellvis24-workflow/preview',body)['plan']
    # Poll only. A failed/uncertain POST is never resent, and a subsequent
    # communication failure requests Stop once, rather than leaving a batch.
    last=None
    dispatched=False
    try:
        try:
            result=api('developer/api/cellvis24-workflow/start',dict(plan=plan,ready=True,path_clear=True,setup_confirmed=True))
        except ApiRejected:
            raise
        except BaseException:
            dispatched=True  # ACK may be lost: never resend Start.
            raise
        dispatched=True
        print(json.dumps(result),flush=True)
        deadline=time.monotonic()+600+600*a.cycles
        while True:
            time.sleep(1);s=api('seq')
            if s.get('name')!='cellvis24_workflow':raise RuntimeError('Workflow ownership changed.')
            logs=s.get('log',[]);message=logs[-1]['msg'] if logs else None
            if message!=last:print(message,flush=True);last=message
            if not s['active']:
                print(json.dumps(s.get('result')),flush=True)
                if s.get('result',{}).get('ok') is not True:raise RuntimeError('Workflow stopped; inspect its receipt. No retry.')
                return s['result']
            if time.monotonic()>deadline:raise TimeoutError('Workflow completion timed out; no retry.')
    except BaseException:
        if dispatched:
            try:api('seq/stop',{})
            except Exception:pass
        raise


if __name__=='__main__':main()
