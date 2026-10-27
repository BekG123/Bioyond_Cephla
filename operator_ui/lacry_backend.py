"""Host-owned Lacry routines. Models select names; they never supply motion."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from researcher_teaching import TeachingError
from scope_step_trial import near, preflight
from scope_compact137 import accepted, HoldingService, pickup_departure_start
from trajectory_queue import LuaTrajectory, prepare_points, travel_program_blocker
from researcher_home import compact_home_connection
from hamilton_prep import HamiltonPrep

class StationConnectionRequired(TeachingError):
    """A station trip needs the separately checked IK Home connector."""

ROOT=Path(__file__).resolve().parent
TRAVEL={'transfer_hamilton_squid','move_home','move_scope','move_hamilton'}
LABELS={
 'retrieve_hamilton_to_squid':'Retrieve from Hamilton and carry to Squid',
 'deliver_hamilton_to_squid':'Retrieve from Hamilton and leave at Squid',
 'squid_dropoff':'Leave plate at Squid', 'squid_retrieve':'Retrieve plate from Squid',
 'hamilton_dropoff':'Leave plate at Hamilton', 'hamilton_retrieve':'Retrieve plate from Hamilton',
 'full_calibration':'Run full calibration', 'camera_calibration':'Calibrate the camera reference',
 'plate_calibration':'Calibrate the two-disk plate',
 'align':'Align with the plate', 'descend':'Descent',
 'grip':'Grip the plate', 'hand_start':'Start human-guided teaching',
 'hand_end':'End human-guided teaching and save', 'deploy_hamilton':'Deploy Hamilton',
 'hamilton_cycles':'Run Hamilton cycles', 'transfer_hamilton_squid':'Transfer Hamilton to Squid',
 'move_home':'Return Home', 'move_scope':'Move to Squid', 'move_hamilton':'Move to Hamilton'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


class LacryBackend:
    def __init__(self,service,runner,camera,draggo,home,hamilton,descent,grip,params,band,teach,aruco,root=None):
        self.s,self.run,self.cam,self.draggo=service,runner,camera,draggo
        self.home,self.hamilton,self.descent,self.grip=home,hamilton,descent,grip
        self.params,self.band,self.teach,self.aruco=params,band,teach,aruco
        self.root=Path(root or ROOT/'demonstrations/lacry')
        self.instrument=HamiltonPrep();self.receipt=None;self.teaching=None
        from squid_adapter import SquidAdapter
        self.squid=SquidAdapter()

    def state(self):
        robot=self.s.status()
        hand=self.draggo.public(robot)
        try:station=self.station(robot['pose_mm'],robot['joints'])
        except (KeyError,TypeError,ValueError,OSError,TeachingError,TransferError):station='Unknown'
        return dict(robot=robot,hand=hand,camera=self.cam.info(),busy=self.run.active,
                    hamilton=self.instrument.status(),squid=self.squid.status(),
                    teaching=self.teaching is not None,station=station,
                    projected_plate_pickup=self.projected_pickup.public() if hasattr(self,'projected_pickup') else None)

    def healthy(self,automatic=True,prepared=True):
        """prepared=False reports state for PLANNING only, skipping the
        Auto/enabled/running gate. Nothing moves, nothing is powered: the
        caller still has to pass prepared=True before any execution. The
        researcher UI prepares the controller after its own confirmation
        (see LacryAgent), so a plan can be drawn up and shown first."""
        state=self.s.status()
        if not state.get('connected'):raise TeachingError('Robot disconnected. Ask your developer to connect it.')
        if not state.get('ok'):raise TeachingError('Robot status unavailable. Check the connection before continuing.')
        if state.get('errors'):raise TeachingError('The robot has a fault. A person must inspect it in Developer view; no reset or restart was sent.')
        if automatic:
            if self.draggo.blocks_motion:raise TeachingError('End human-guided teaching before automatic movement.')
            if prepared:
                if not state.get('enabled') or state.get('control_mode',{}).get('mode')!='auto' or state.get('program_state',{}).get('state')!='running':
                    raise TeachingError('Automatic movement is not ready. Have your developer prepare the controller; Lacry will not enable or restart it.')
                preflight(self.s)
        return state

    def evidence(self):
        plan,forward,hashes,trials=accepted()
        path=ROOT/'reports/squid/compact4_20261017T131133Z_ace8e9/compact4_roundtrip_speed137_trial.json'
        raw=path.read_bytes();fast=json.loads(raw)
        if fast.get('status')!='completed' or fast['plan']['sources']!=hashes:
            raise TeachingError('The tested microscope route needs developer review.')
        hashes['speed137']=hashlib.sha256(raw).hexdigest()
        _,source_id,ham=self.hamilton.reviewed()
        hashes['hamilton']=digest(ham);hashes['hamilton_source']=source_id
        hashes['home']=self.home.target()[1]
        from scope_compact137 import speed_policy
        hashes['scope_speed_policy']=digest(speed_policy())
        from hamilton_true_home import candidate
        hashes['hamilton_true_home']=digest(candidate(self.home.target()[0],self.s.envelope))
        return forward,hashes,trials,plan

    def station(self,pose,joints):
        forward,_,trials,_=self.evidence()
        original,_,ham=self.hamilton.reviewed()
        from hamilton_true_home import station_reference
        ham_pose,ham_q=station_reference(original)
        stations=[('Home',forward[0],trials['reverse']['final_robot']['joints']),
                  ('Squid',forward[-1],trials['forward']['final_robot']['joints']),
                  ('Hamilton',ham_pose,ham_q)]
        for name,target,q in stations:
            try:
                near(pose,target,.2)
                if any(abs(joints[k]-q[k])>.5 for k in ('J1','J2','J3','J4')):continue
                return name
            except (TransferError,KeyError):pass
        from hamilton_true_home import candidate,departure_start,measured_departure
        review = candidate(forward[0],self.s.envelope)
        measured = measured_departure(pose, review)
        if measured is not None:
            if all(abs(joints[k]-measured['joints'][k]) <= .5 for k in ('J1','J2','J3','J4')):
                return 'Hamilton'
            return 'Other position'
        if departure_start(pose,review):
            ham_q['J1']+=pose['Z']-ham_pose['Z']
            if joints['J1']>=0 and all(abs(joints[k]-ham_q[k])<=.5 for k in ('J1','J2','J3','J4')):
                return 'Hamilton'
        if pickup_departure_start(pose, forward):
            q = dict(trials['forward']['final_robot']['joints'])
            q['J1'] += pose['Z'] - forward[-1]['Z']
            if all(abs(joints[k]-q[k]) <= .5 for k in ('J1','J2','J3','J4')):
                return 'Squid'
        return 'Other position'

    def plan_travel(self,action,pose,q):
        forward,hashes,trials,scope_plan=self.evidence()
        cfg=self.params();env=self.s.envelope
        if cfg!=scope_plan['params'] or any(list(env[k])!=scope_plan['envelope'][k] for k in ('X','Y','Z')):
            raise TeachingError('Travel settings changed since the microscope trial. Ask the developer to review them.')
        self.hamilton.check_previous_attempt()
        station=self.station(pose,q);stages=[];current=dict(pose);joints=dict(q)
        def append(label,points,profile):
            nonlocal current,joints
            start=dict(current);start_q=dict(joints)
            points,_=prepare_points(start,joints,points,cfg,reviewed=True,**profile)
            path_env=self.travel_envelope(start,points,profile)
            if profile.get('hamilton_home'):
                from hamilton_true_home import check_route
                check_route(start,points,joints,cfg,env)
            offset=joints['J1']-current['Z']
            for target in points:
                joints=check_path(current,target,joints,cfg,path_env)
                if not 0<=target['Z']+offset<=400 or abs(joints['J3'])>180:raise TransferError('Travel limit exceeded')
                joints['J1']=target['Z']+offset;current=target
            stages.append(dict(kind='travel',label=label,start=start,joints=start_q,points=points,profile=profile,sources=hashes))
        def to_home():
            if station=='Home':return
            if station=='Squid':
                append('Leave the microscope and return Home',list(reversed(forward))[1:],dict(scope_compact=True));return
            if station=='Hamilton':
                from hamilton_true_home import candidate
                route=candidate(forward[0],env)
                append('Return directly from Hamilton to true Home',route['reverse'][1:],dict(hamilton_home=True))
                return
            raise StationConnectionRequired('This position needs a checked return to Home before station travel.')
        if action=='transfer_hamilton_squid' and station!='Hamilton':
            raise TeachingError('Send to Squid must start at Hamilton with the plate already held, or as a confirmed empty rehearsal. The arm is '+station+'.')
        destination={'move_home':'Home','move_hamilton':'Hamilton','move_scope':'Squid','transfer_hamilton_squid':'Squid'}[action]
        if station==destination:raise TeachingError('The arm is already at '+destination+'.')
        to_home()
        if destination=='Squid':
            expected=trials['reverse']['final_robot']['joints']
            if any(abs(joints[k]-expected[k])>.5 for k in ('J1','J2','J3','J4')):
                raise TeachingError('The return does not reach the tested microscope starting configuration. Ask your developer to review it.')
            append('Move to the microscope using the tested approach',forward[1:],dict(scope_compact=True))
        elif destination=='Hamilton':
            from hamilton_true_home import candidate
            route=candidate(forward[0],env)
            append('Travel from true Home to the taught Hamilton entrance',route['forward'][1:],dict(hamilton_home=True))
        return stages,current,joints

    def travel_envelope(self,start,points,profile):
        """Honor only the existing hash-bound Hamilton route's box exception.

        Home connectors and microscope travel still use the normal box. Joint,
        reach and linear-axis checks apply to every leg, including Hamilton.
        """
        if profile.get('hamilton_home'):
            from hamilton_true_home import validate_route
            validate_route(start,points)
            # check_route applies the normal box to the new connector; only
            # the exact inherited Hamilton prefix has its old exception.
            return None
        if not (profile.get('forward_entry') or profile.get('reverse_entry')):
            return self.s.envelope
        _,_,route=self.hamilton.reviewed()  # verifies recording, grant and hashes
        expected=[route['start']]+route['points']
        if profile.get('reverse_entry'):
            expected=list(reversed(expected))
        near(start,expected[0],.2)
        if len(points)!=len(expected)-1:
            raise TeachingError('Hamilton route differs from the taught path.')
        for actual,target in zip(points,expected[1:]):
            near(actual,target,.011)
        return None

    def compile(self,actions,prepared=True):
        from station_transfer import ALIASES, SEQUENCES
        if (len(actions)==1 and actions[0] in ALIASES) or actions in SEQUENCES:
            from station_transfer import plan
            return plan(self,actions)
        if set(actions)&{'squid_dropoff','squid_retrieve','hamilton_dropoff','hamilton_retrieve'}:
            if len(actions)!=1:
                raise TeachingError('For delivery, imaging and retrieval together, use the complete Squid experiment workflow with one confirmation. A generic station-action list cannot track imaging completion.')
            from squid_handling import plan
            return plan(self,actions[0])
        if 'full_calibration' in actions:
            raise TeachingError('This action combination is not supported. Full calibration is automatic '
                                'using the camera and saved pickup routine; it does not require hand-guided teaching. '
                                'Use full calibration, optionally preceded by Return Home and followed by Move to Squid.')
        if any(a not in LABELS for a in actions):raise TeachingError('That lab action is not available.')
        if any(a in ('deploy_hamilton','hamilton_cycles') for a in actions):
            raise TeachingError('Hamilton instrument control and repeated cycles are coming soon. The transfer route can be tested separately.')
        state=self.healthy(automatic=not all(a in ('hand_start','hand_end') for a in actions),prepared=prepared)
        self.camera_plate_only(actions,state)
        if any(a in ('hand_start','hand_end') for a in actions) and len(actions)!=1:
            raise TeachingError('Start or end human-guided teaching separately from automatic work.')
        if self.run.active:raise TeachingError('Wait for the current lab task to finish.')
        if actions==['hand_start'] and not self.draggo.public(state).get('can_start'):
            raise TeachingError('Human-guided teaching is not ready. Check that the arm is still and supported.')
        if actions==['hand_end'] and not self.draggo.public(state).get('can_end'):
            raise TeachingError('Human-guided teaching is not active.')
        pose=deepcopy(state.get('pose_mm'));q=deepcopy(state.get('joints'));steps=[]
        dynamic=False;prior=set()
        for action_index,action in enumerate(actions):
            if action in TRAVEL:
                if dynamic:raise TeachingError('Complete and inspect the plate operation before requesting travel.')
                stages,pose,q=self.plan_travel(action,pose,q)
                for stage in stages:stage['action_index']=action_index
                steps.extend(stages)
            elif action=='camera_calibration':
                if not self.cam.info().get('enabled'):raise TeachingError('Camera disconnected. Open Camera View and reconnect it before calibration.')
                steps.extend(dict(kind=k,label=v) for k,v in [('disk_find','Find the calibration plate'),('disk_id','Check the plate marker'),('camera_calibration','Calibrate the camera'),('anchor','Generate and verify the calibration reference')]);dynamic=True
            else:
                if action in ('plate_calibration','align','descend','grip'):dynamic=True
                if action=='align' and not {'plate_calibration','camera_calibration'}&prior:self.require_receipt('calibrated')
                if action=='descend' and 'align' not in prior:self.require_receipt('aligned')
                if action=='grip' and 'descend' not in prior:self.grip._ready(state)
                steps.append(dict(kind=action,label=LABELS[action]))
            prior.add(action)
        if any(s['kind']=='travel' for s in steps):
            cap=LuaTrajectory(self.s).capability()
            # Read-only plans may precede the existing explicit, empty-gripper
            # startup. A stopped Lua app cannot advertise its queue version.
            blocker=travel_program_blocker(cap, allow_initialization=(not prepared and
                state.get('program_state',{}).get('state') in ('stopped','paused')))
            if blocker:raise TeachingError(blocker)
        requirements=['Keep the route clear, release the arm, and supervise the emergency stop.']
        if any(s.get('profile',{}).get('hamilton_home') for s in steps):
            from hamilton_true_home import candidate, requirement
            requirements.append(requirement(candidate(self.home.target()[0],self.s.envelope)))
        if actions==['hand_start']:requirements=['Support the still arm, remove any plate from the gripper, keep the area clear, and supervise the emergency stop.']
        elif actions==['hand_end']:requirements=['Keep the arm and anything it holds still and supported while hand-guiding ends.']
        elif any(a in ('camera_calibration','plate_calibration','align','descend') for a in actions):requirements.append('The gripper is empty and the calibration plate remains fixed and visible.')
        if 'camera_calibration' in actions:requirements.append('The marked plate is on a contrasting surface; the full camera calibration sweep is clear. You will review its detected outline before the reference is saved.')
        if 'grip' in actions:requirements.append('The plate is supported and centered. Inspect the grip before requesting a lift.')
        if 'transfer_hamilton_squid' in actions:requirements.append('The plate is already securely held, or this is an empty rehearsal. This run does not pick up or release a plate.')
        elif any(a in TRAVEL for a in actions):requirements.append('Any held plate is secure. This run leaves the gripper unchanged.')
        summary=''
        if len(actions)==1 and actions[0] in TRAVEL:
            origin=self.station(state['pose_mm'],state['joints'])
            destination={'move_home':'Home','move_scope':'Squid','move_hamilton':'Hamilton','transfer_hamilton_squid':'Squid'}[actions[0]]
            stops=[origin]+(['Home'] if origin!='Home' and destination!='Home' else [])+[destination]
            summary=' → '.join(stops)+' using the taught routes.'
        if any(s.get('profile',{}).get('hamilton_home') for s in steps):
            summary=(summary.replace('using the taught routes.', '') +
                     'The direct Hamilton/Home connector needs clearance review.')
        return dict(actions=actions,steps=steps,requirements=requirements,summary=summary,start=state.get('pose_mm'),joints=state.get('joints'),
                    cfg=self.params(),envelope={k:list(v) for k,v in self.s.envelope.items()},e1=state.get('external_axes',{}).get('E1'))

    def pickup_to_scope_plan(self):
        """Plan the saved Home-to-Squid route after the accepted pickup.

        Projected Home feedback is evidence for planning only. The actual
        post-pickup position, joints, grip and running Auto state are checked
        before dispatch, without enabling or restarting a loaded controller.
        """
        forward, _, trials, _ = self.evidence()
        home, ident = self.home.target()
        near(home, forward[0], .001)
        joints = deepcopy(trials['reverse']['final_robot']['joints'])
        steps, _, _ = self.plan_travel('move_scope', home, joints)
        return dict(actions=['move_scope'], labels=['Move to Squid'], steps=steps,
                    start=deepcopy(home), joints=joints, e1=3.7, target_id=ident,
                    cfg=deepcopy(self.params()), envelope={k:list(v) for k,v in self.s.envelope.items()},
                    prepare=False, requirements=[
                        'The loaded Home-to-Squid route and final seating descent are clear.',
                        'The Squid holder is ready at its taught loading position. The plate stays held; '
                        'this does not release it or start imaging.'],
                    summary='After pickup returns Home, travel to Squid at 137 with final descent at 10.')

    def verify_pickup_to_scope_plan(self, plan):
        if self.pickup_to_scope_plan() != plan:
            raise TeachingError('The post-calibration Squid route or settings changed. Request a fresh complete plan.')

    def transport_rehearsal(self,repetitions):
        """Explicit transport only; never starts instruments or changes jaws."""
        if type(repetitions) is not int or not 1<=repetitions<=100:
            raise TeachingError('Choose a whole number of rounds from 1 to 100.',400)
        state=self.healthy()  # Already prepared: startup could close held jaws.
        if self.station(state['pose_mm'],state['joints'])!='Home':
            raise TeachingError('Return to saved Home before starting the transport rehearsal.')
        plan=self.compile(['move_hamilton','move_scope','move_home']*repetitions)
        route_reviews=[r for r in plan['requirements'] if r.startswith('New direct Hamilton/Home connector:')]
        for step in plan['steps']:
            step['cycle']=step['action_index']//3+1
            step['label']=f"Round {step['cycle']}/{repetitions}: "+step['label']
        plan.update(repetitions=repetitions,transport_only=True,prepare=False,
            labels=[f'{repetitions}-round transport rehearsal'],
            summary=f'{repetitions} rounds: Home → Hamilton → Home → Squid → Home. Transit at 137; final Squid descent at 10. Keep the plate held throughout.',
            requirements=[
                'The plate is securely held; the full loaded route and station approaches are clear.',
                'The arm is released, hands are clear, and the emergency stop is supervised.',
                'Transport only: no dispensing, imaging, pickup, release or gripper commands. Any failure stops the remaining rounds.'])
        plan['requirements'].extend(route_reviews)
        return plan

    def camera_plate_only(self,actions,state=None):
        if not set(actions)&{'full_calibration','camera_calibration','plate_calibration','align','descend','grip'}:
            return
        state=state or self.s.status()
        pose=state.get('pose_mm')
        if not pose:
            raise TeachingError('Robot position unavailable; cannot check the camera plate location.')
        forward,_,_,_=self.evidence()
        original,_,_=self.hamilton.reviewed()
        # Position-based exclusion also applies when the wrist winding differs.
        from hamilton_true_home import station_reference
        for name,target in [('Squid',forward[-1]),('Hamilton',station_reference(original)[0]),
                            ('Hamilton',original['trajectory'][0]['pose_mm'])]:
            try:near(pose,target,2.)
            except TransferError:continue
            raise TeachingError(f'The arm is at {name}. Camera plate calibration and pickup are not station handling. '
                                f'Use the taught {name} pickup/release sequence; its local handling still needs teaching.')

    def require_receipt(self,phase):
        if not self.receipt or self.receipt['phase']!=phase or time.time()-self.receipt['at']>600:
            raise TeachingError('Run '+('plate calibration' if phase=='calibrated' else 'alignment')+' first to create a fresh plate reference.')
        near(self.s.pose_mm(),self.receipt['pose'],.1)
        return deepcopy(self.receipt['target'])

    def remember(self,phase,target):
        self.receipt=dict(phase=phase,at=time.time(),pose=self.s.pose_mm(),target=deepcopy(target))

    def verify_confirmation(self,plan,prepared=True):
        if plan.get('dispatch')=='station_transfer':
            from station_transfer import verify
            verify(self,plan)
        if plan.get('dispatch') in ('squid_handling','hamilton_handling'):
            from squid_handling import verify
            verify(self,plan)
        automatic=not all(a in ('hand_start','hand_end') for a in plan['actions'])
        state=self.healthy(automatic,prepared=prepared)
        if self.run.active:raise TeachingError('Another lab task is running.')
        if self.params()!=plan['cfg'] or {k:list(v) for k,v in self.s.envelope.items()}!=plan['envelope']:
            raise TeachingError('Settings changed. Ask Lacry for a fresh plan.')
        # During teaching the human is expected to have moved the arm.
        if plan['actions']!=['hand_end']:
            near(state['pose_mm'],plan['start'],.2)
            if any(abs(state['joints'][k]-plan['joints'][k])>.5 for k in ('J1','J2','J3','J4')):
                raise TeachingError('The arm moved since this plan. Ask for a fresh plan.')
            if type(plan['e1']) not in (float,int) or abs(self.s.external_axes().get('E1',float('inf'))-plan['e1'])>.1:
                raise TeachingError('The gripper changed. Ask for a fresh plan.')
        for step in plan['steps']:
            if step['kind']=='travel' and step['sources']!=self.evidence()[1]:raise TeachingError('The tested route changed. Request a fresh plan.')

    def execute_step(self,run,step,plan):
        kind=step['kind']
        if run.stopped():raise TeachingError('Stopped before the next action.')
        if plan.get('dispatch')=='station_transfer':
            from station_transfer import execute_step
            return execute_step(self,run,step,plan)
        if kind in ('hand_start','hand_end'):return self.hand_guiding(kind=='hand_start')
        self.healthy()
        self.camera_plate_only([kind])
        if plan.get('dispatch') in ('squid_handling','hamilton_handling'):
            from squid_handling import context, execute_local
            if context(plan['actions'][0])[3]!=plan['handling_evidence']:
                raise TeachingError('Station handling reference changed during the run.')
            if self.params()!=plan['cfg'] or {k:list(v) for k,v in self.s.envelope.items()}!=plan['envelope']:
                raise TeachingError('Squid settings changed during the run.')
            if kind in ('squid_jaw','squid_lift','hamilton_jaw','hamilton_lift','hamilton_inspect'):
                return execute_local(self,run,step,plan)
        if kind=='travel':
            blocker=travel_program_blocker(LuaTrajectory(self.s).capability())
            if blocker:raise TeachingError(blocker)
            if step['sources']!=self.evidence()[1]:raise TeachingError('Tested route changed during this run.')
            near(self.s.pose_mm(),step['start'],.2)
            if any(abs(self.s.joints()[k]-step['joints'][k])>.5 for k in ('J1','J2','J3','J4')):raise TeachingError('Travel starting configuration changed.')
            current=self.s.pose_mm();q=self.s.joints()
            path_env=self.travel_envelope(current,step['points'],step['profile'])
            if step['profile'].get('hamilton_home'):
                from hamilton_true_home import check_route
                check_route(current,step['points'],q,self.params(),self.s.envelope)
            for point in step['points']:q=check_path(current,point,q,self.params(),path_env);current=point
            profile=step['profile'];speed_profile=('scope_speed137' if profile.get('scope_compact') else 'home_speed137' if profile.get('straight_transfer') or profile.get('hamilton_home') else 'research_speed137')
            held_e1=step['expected_e1'] if plan.get('dispatch') in ('squid_handling','hamilton_handling') else plan['e1']
            holding=HoldingService(self.s,held_e1,plan['envelope'])
            def progress(stage,done,total):
                run.audit('lacry_travel_progress',stage=stage,done=done,total=total,
                          pose=self.s.pose_mm(),joints=self.s.joints(),e1=self.s.external_axes())
            if profile.get('scope_compact'):
                from scope_compact137 import execute_route
                result=execute_route(run,holding,step['start'],self.s.joints(),
                                     step['points'],self.params(),progress)
            else:
                result=LuaTrajectory(holding).execute(run,step['start'],self.s.joints(),step['points'],self.params(),137,
                    progress,reviewed=True,**profile,**{speed_profile:True})
            near(self.s.pose_mm(),step['points'][-1],.2);self.receipt=None
            return result
        from sequences import seq_calibrate_aruco,seq_calibrate_camera,seq_generate_anchor,seq_align
        if kind in ('disk_find','plate_calibration'):
            from pick_and_hold.Calibration.fast_disk import run_fast_disk,CalibrationTrace
            self.receipt=None
            trace=CalibrationTrace(str(ROOT/'reports/calibration'),'automatic','Wide')
            result=run_fast_disk(run,self.s,self.cam,self.teach,self.params(),config='Wide',trace=trace)
            if result.get('ok') and result.get('target',{}).get('converged'):self.remember('calibrated',result['target'])
            elif result.get('ok'):raise TeachingError('Calibration did not confirm convergence.')
            return result
        if kind=='disk_id':return seq_calibrate_aruco(run,self.s,self.cam,self.aruco)
        if kind=='camera_calibration':return seq_calibrate_camera(run,self.s,self.cam,self.aruco)
        if kind=='anchor':
            result=seq_generate_anchor(run,self.s,self.cam,self.teach,self.aruco)
            if result.get('ok'):
                if not result.get('anchor_pending') or len(result.get('pending_rows',[]))!=2:raise TeachingError('Calibration reference is incomplete.')
                result.update(review_required=True,review_pose=self.s.pose_mm())
            return result
        if kind=='align':
            target=self.require_receipt('calibrated');run.target=target
            result=seq_align(run,self.s,target,0,validate_descent=False)
            if result.get('ok'):self.remember('aligned',target)
            return result
        if kind=='descend':
            target=self.require_receipt('aligned')
            # Preconditions already require running Auto. Never use the old auto-prepare callback.
            from researcher_descent import ResearcherDescent
            descent=ResearcherDescent(lambda:self.s,lambda:run,self.params,self.band,
                                      lambda *_:self.healthy(),self.grip.completed_descent)
            result=descent.execute(run,self.s,target,self.s.pose_mm())
            self.receipt=None
            return result
        if kind=='grip':
            self.grip._ready(self.s.status());receipt=deepcopy(self.grip.receipt);self.grip.invalidate()
            return self.grip.execute(run,receipt)
        raise TeachingError('This action is not connected yet.')

    def finish_anchor(self,run,result):
        self.healthy();near(self.s.pose_mm(),result['review_pose'],.1)
        if run.stopped():raise TeachingError('Stopped before saving the calibration reference.')
        for row in result['pending_rows']:self.aruco.save_anchor(row)
        derived=self.aruco.derive_arm_from_anchors()
        if not derived.get('ok'):raise TeachingError('The saved reference did not verify against the camera calibration.')
        # Disk offsets calibrated before the mount fit must be refreshed under it.
        from sequences import seq_calibrate_aruco
        verified=seq_calibrate_aruco(run,self.s,self.cam,self.aruco)
        if not verified.get('ok'):return verified
        stamps=self.aruco.model_stamps()
        if not stamps[0] or stamps[0]!=stamps[1]:raise TeachingError('Camera and grip reference versions do not agree.')
        self.receipt=None
        return dict(ok=True,calibration_verified=True,arm=derived,disk=verified)

    def hand_guiding(self,start):
        if start:
            self.root.mkdir(parents=True,exist_ok=True)
            folder=self.root/('teaching_'+uuid4().hex);folder.mkdir()
            manifest=dict(status='starting',started_at=time.time(),kind='human_guided_motion',reviewed=False,executable=False)
            (folder/'session.json').write_text(json.dumps(manifest,indent=2))
            result=self.draggo.change(True,ready=True)
            if not result.get('ok'):return result
            import threading
            stop=threading.Event();self.teaching=dict(folder=folder,stop=stop,manifest=manifest,samples=0,error=None)
            session=self.teaching
            def record():
                try:
                    with (folder/'samples.jsonl').open('x',encoding='utf-8') as stream:
                        while not stop.is_set():
                            state=self.s.status()
                            if not state.get('ok') or not state.get('pose_mm') or not state.get('joints'):raise RuntimeError('Teaching position feedback unavailable')
                            stream.write(json.dumps(dict(at=time.time(),robot=state),allow_nan=False)+'\n');stream.flush();session['samples']+=1
                            stop.wait(.2)
                except Exception as error:session['error']=str(error)
            thread=threading.Thread(target=record,daemon=True,name='lacry-teaching');session['thread']=thread;thread.start()
            self.receipt=None;self.grip.invalidate()
            return dict(ok=True,teaching=True,message='Human-guided teaching is active and recording. Guide gently; keep the arm supported.')
        result=self.draggo.change(False)
        if not result.get('ok'):return result
        if self.teaching:
            session=self.teaching;session['stop'].set();session['thread'].join(timeout=3)
            if session['thread'].is_alive():raise TeachingError('Hand-guiding ended, but the recording is still closing. Ask your developer to inspect it.')
            session['manifest'].update(status='incomplete' if session['error'] else 'recorded',finished_at=time.time(),samples=session['samples'],error=session['error'])
            (session['folder']/'session.json').write_text(json.dumps(session['manifest'],indent=2))
            self.teaching=None
            if session['error']:raise TeachingError('Hand-guiding ended. Some recording data is missing; ask your developer to review it.')
            return dict(ok=True,message='Human-guided teaching ended and your demonstration is saved for developer review.')
        return dict(ok=True,message='Human-guided teaching ended. No Lacry recording was active.')
