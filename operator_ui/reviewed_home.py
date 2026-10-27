"""Explicit developer-reviewed, repeatable Home connection for Lacry.

No arbitrary-position fallback: a saved review must match the live start,
settings and route. Physical clearance is confirmed on the existing GUI card.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from autonomy import wrap
from researcher_teaching import TeachingError

ROOT=Path(__file__).resolve().parent
REGISTRY=ROOT/'reviewed_home_connection.json'


class ReviewedHomeConnection:
    def __init__(self,home,registry=REGISTRY):
        self.home,self.registry=home,Path(registry)

    def load(self):
        if not self.registry.exists():return None
        entry=json.loads(self.registry.read_text(encoding='utf-8'))
        path=(ROOT/entry['review']).resolve()
        if path.parent!=(ROOT/'reports/alignment_home').resolve():
            raise TeachingError('Home review location is invalid.')
        raw=path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=entry['sha256']:raise TeachingError('Home review changed. Ask your developer to review it again.')
        review=json.loads(raw)
        if review.get('schema')!='cephla.alignment-home-review.v1' or not review.get('ik_and_limits_passed'):
            raise TeachingError('Home route review is incomplete.')
        return path,digest,review

    @staticmethod
    def previous_attempts(path,digest):
        """Successful returns are reusable; unfinished/failed runs need review.

        Preserve the legacy single-attempt record and append new per-run files.
        A new plan and confirmation are required for each execution.
        """
        legacy=path.with_name(path.stem+'_gui_attempt.json')
        folder=path.with_name(path.stem+'_gui_attempts')
        paths=([legacy] if legacy.exists() else [])+sorted(folder.glob('*.json'))
        records=[]
        for attempt in paths:
            record = None
            try:
                record=json.loads(attempt.read_text(encoding='utf-8'))
                sequence=record.get('sequence') or {}
                complete=(record.get('review_sha256')==digest and record.get('status')=='completed'
                          and sequence.get('state')=='done'
                          and (sequence.get('result') or {}).get('ok') is True)
            except (OSError,ValueError,TypeError,AttributeError):
                complete=False
            from home_attempts import known_startup_refusal, UNCERTAIN_MESSAGE
            refused = (known_startup_refusal(record)
                       and record.get('review_sha256') == digest)
            if not complete and not refused:
                raise TeachingError(UNCERTAIN_MESSAGE)
            records.append(record)
        return records

    @staticmethod
    def same_stages(actual,expected):
        if len(actual)!=len(expected):return False
        for a,b in zip(actual,expected):
            if a['kind']!=b['kind']:return False
            if a['kind']=='rotate':
                if abs(wrap(a['rz']-b['rz']))>.02:return False
            else:
                if len(a['points'])!=len(b['points']):return False
                for p,q in zip(a['points'],b['points']):
                    if any(abs(p[k]-q[k])>.02 for k in ('X','Y','Z','Rz')):return False
        return True

    def propose(self):
        loaded=self.load()
        if loaded is None:return None
        path,digest,review=loaded
        self.previous_attempts(path,digest)
        svc=self.home.get_service();run=self.home.get_runner();state=svc.status()
        if run.active or getattr(run,'reserved',False):raise TeachingError('Wait for the current action to finish.')
        if not state.get('ok') or not state.get('connected') or state.get('errors'):
            raise TeachingError('Resolve the robot alert or connection before returning Home.')
        hand=self.home.get_draggo().public(state)
        if hand.get('state')!='off':raise TeachingError('End human-guided teaching before reviewing this Home return.')
        pose,joints=state['pose_mm'],state['joints']
        for k in ('X','Y','Z','Rz'):
            delta=pose[k]-review['start'][k]
            if k=='Rz':delta=wrap(delta)
            if abs(delta)>.05:
                raise TeachingError('The arm is outside the reviewed Home-return start. Ask your developer to review the connection from this position.')
        if any(abs(joints[k]-review['start_joints'][k])>.1 for k in ('J1','J2','J3','J4')):
            raise TeachingError('The arm configuration differs from the Home review.')
        if abs(state['external_axes']['E1']-review['observed_e1'])>.05:
            raise TeachingError('The gripper changed since the Home review.')
        if self.home.params()!=review['config'] or not svc.envelope_enabled or {k:list(v) for k,v in svc.envelope.items()}!=review['envelope']:
            raise TeachingError('Settings changed since the Home review.')
        target,ident=self.home.target()
        if target!=review['home'] or ident!=review['target_id']:
            raise TeachingError('Saved Home changed since review.')
        if hashlib.sha256(self.home.path.read_bytes()).hexdigest()!=review['points_sha256']:
            raise TeachingError('Saved positions changed since the Home review.')
        route=self.home.route_plan(pose,target,joints,self.home.params(),svc.envelope)
        if route.get('prefix') or not self.same_stages(route.get('stages',[]),review['stages']):
            raise TeachingError('Home path differs from the reviewed connection.')
        labels=[]
        for stage in review['stages']:
            if stage['kind']=='rotate':labels.append('Turn the wrist at clearance height')
            else:
                for point in stage['points']:
                    labels.append('Move to X%.2f / Y%.2f / Z%.2f mm'%(point['X'],point['Y'],point['Z']))
        return dict(actions=['move_home'],labels=['Return Home'],dispatch='reviewed_home_return',
            target_id=ident,review_sha256=digest,review_path=str(path),
            steps=[dict(kind='home_return',label=s) for s in labels],
            requirements=['The gripper is empty; remove anything it held.',
                'Confirm the listed lift, wrist sweep, crossing and lowering are clear. Release the arm, keep hands clear and supervise the E-stop.',
                'Auto preparation may start the controller program and close the empty jaws.'],
            summary='Return Home using the connection checked for this exact starting position. Translation 137; wrist 30. Confirm physical clearance before running.')

    def start(self,plan):
        fresh=self.propose()
        if fresh is None or any(fresh[k]!=plan[k] for k in ('review_sha256','target_id','review_path','steps')):
            raise TeachingError('Home review changed. Request a fresh plan.')
        path=Path(fresh['review_path'])
        previous=self.previous_attempts(path,fresh['review_sha256'])
        if any(r.get('plan_id')==plan['id'] for r in previous):
            raise TeachingError('This confirmation was already used. Request Return Home again for a new run.')
        folder=path.with_name(path.stem+'_gui_attempts')
        folder.mkdir(exist_ok=True)
        attempt=folder/(str(time.time_ns())+'_'+uuid4().hex+'.json')
        record=dict(status='confirmed',at=time.time(),review_sha256=fresh['review_sha256'],
            requirements_confirmed=fresh['requirements'],plan_id=plan['id'])
        with attempt.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
        try:
            result=self.home.start(dict(ready=True,target_id=fresh['target_id']))
            record.update(status='started',response=result)
        except Exception as error:
            record.update(status='failed_to_start',error=str(error));raise
        finally:attempt.write_text(json.dumps(record,indent=2),encoding='utf-8')
        return result,attempt

    def finish(self,attempt,sequence):
        record=json.loads(Path(attempt).read_text(encoding='utf-8'))
        record.update(finished_at=time.time(),sequence=deepcopy(sequence),
            status='completed' if sequence['state']=='done' and (sequence.get('result') or {}).get('ok') else 'failed_or_stopped')
        evidence = (sequence.get('result') or {}).get('home_startup_refusal')
        record.pop('home_startup_refusal', None)
        if evidence is not None:
            record['home_startup_refusal'] = deepcopy(evidence)
        Path(attempt).write_text(json.dumps(record,indent=2),encoding='utf-8')
