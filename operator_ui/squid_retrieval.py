"""One confirmed continuation of an acquisition started in Squid's GUI.

No imaging starts, no native stage homing, no model-provided coordinates.
"""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from autonomous_squid import AutonomousSquid
from researcher_teaching import TeachingError
from squid_execution import at_position,digest

ROOT=Path(__file__).resolve().parent


class SquidRetrieval:
    def __init__(self,agent,stage=None,folder=None):
        self.agent=agent;self.backend=agent.backend
        self.stage=stage or agent.squid_stage()
        self.folder=Path(folder or ROOT/'reports/squid_retrieval')
        self.thread=None;self.cancel=threading.Event()

    @property
    def active(self):return bool(self.thread and self.thread.is_alive())

    def records(self):
        for path in self.folder.glob('*/workflow.json'):
            try:yield json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):raise TeachingError('A Squid retrieval record is unreadable; review it before another run.') from None

    def check_history(self,stage):
        for record in self.records():
            if record['status'] in ('confirmed','running'):
                raise TeachingError('An earlier Squid retrieval has no recorded ending. Review it before another run.')
            previous=record['plan']['stage']
            if (record['status']=='completed' and previous['session']==stage['session']
                    and previous['job']['run_id']==stage['job']['run_id']):
                raise TeachingError('This imaging job already had a successful plate retrieval. No repeat was queued.')

    def propose(self,only_if_idle=False,expected_event=None):
        with self.agent.lock:
            if only_if_idle and (self.agent.busy or self.agent.pending or self.agent.review):return None
            if not only_if_idle:self.agent.pending=None
        stage=self.stage.propose('dropoff',after_scan=True,_publish=False)
        if not stage.get('job'):
            raise TeachingError('No current tracked acquisition is running or confirmed complete. Check Squid acquisition status; do not repeat drop-off.')
        if expected_event and (stage['session']!=expected_event['session']
                or stage['job']['run_id']!=expected_event['job']['run_id']):
            raise TeachingError('The observed Squid job changed before retrieval was proposed.')
        self.check_history(stage)
        if self.stage.saved().get('accepted_for_robot_loading') is not True:
            raise TeachingError('The Squid loading position has not been accepted for robot retrieval.')
        retrieval=self.agent.automatic_workflow().projected_handling('squid_retrieve')
        self.backend.verify_confirmation(retrieval,prepared=True)
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='squid_retrieval',actions=['retrieve_after_squid'],
            labels=['Retrieve plate after Squid imaging'],executable=True,stage=stage,retrieval=retrieval,
            steps=stage['steps']+retrieval['steps'],
            summary='Wait for the tracked Squid acquisition to finish, return its stage to the saved loading position, then retrieve the plate to Home.',
            requirements=['The plate is seated in Squid; the empty arm is at Home with its jaws ready for retrieval.',
                'The stage return, pickup and loaded Home route are clear; keep hands clear and supervise the E-stop.',
                'One Yes covers waiting, returning the stage and retrieving this plate. No new imaging or calibration is started.',
                'Stop prevents further movement after the current command; it does not abort imaging started in Squid.'])
        if self.stage.adapter.status().get('camera_simulated'):
            plan['requirements'].append('Squid camera images are simulated; stage and robot movements are physical.')
        with self.agent.lock:
            if only_if_idle and (self.agent.busy or self.agent.pending or self.agent.review):return None
            self.agent.pending=plan
        self.agent._announce_plan(plan)
        return deepcopy(plan)

    def verify(self,plan):
        self.check_history(plan['stage'])
        self.stage.arm_clear()
        self.stage.check_job(plan['stage'],self.stage.ready(plan['stage']))
        if self.stage.saved().get('accepted_for_robot_loading') is not True:
            raise TeachingError('The Squid loading position needs review.')
        actual=self.agent.automatic_workflow().projected_handling('squid_retrieve')
        if digest(actual)!=digest(plan['retrieval']):raise TeachingError('The retrieval route changed. Request a fresh plan.')
        self.backend.verify_confirmation(plan['retrieval'],prepared=True)

    def start(self,plan):
        self.verify(plan)
        if self.active:raise TeachingError('Squid retrieval is already running.')
        if any(r['plan']['id']==plan['id'] for r in self.records()):raise TeachingError('This confirmation has already been used.')
        folder=self.folder/plan['id'];folder.mkdir(parents=True,exist_ok=False)
        record=dict(status='confirmed',plan=deepcopy(plan),events=[])
        path=folder/'workflow.json'
        save=lambda:AutonomousSquid.write(path,record)
        save()
        run=self.agent.get_runner();token=object();self.cancel=threading.Event()
        if not run.reserve(token,self.cancel):
            record['status']='not_started';save();raise TeachingError('Another workflow owns the arm.')
        with self.agent.lock:
            self.agent.pending=None
            self.agent.run_meta=dict(name=plan['labels'][0],total_steps=len(plan['steps']),automatic=True)
            self.agent.run_state=dict(active=True,step=plan['steps'][0]['label'],done=[],ok=None,error='',message='Waiting for Squid, then returning the plate Home.')

        def worker():
            done=[]
            def check():
                if self.cancel.is_set() or run.stopped():raise TeachingError('Stopped. No subsequent retrieval step was started.')
            def execute_job(label,fn):
                check()
                record['events'].append(dict(at=time.time(),phase=label,status='requested'));save()
                with self.agent.lock:self.agent.run_state.update(step=label,done=list(done),message=label)
                if not run.start('lacry_squid_retrieval',fn).get('ok'):raise TeachingError('Could not start '+label)
                run._thread.join(86460)
                if run.active:run.request_stop();raise TeachingError('Command timed out; completion is uncertain.')
                check()
                if (run.result or {}).get('ok') is not True:raise TeachingError((run.result or {}).get('error') or label+' did not complete.')
                record['events'].append(dict(at=time.time(),phase=label,status='completed',result=deepcopy(run.result)));save()
            def loading_ready():
                if not self.stage.check_job(plan['stage'],self.stage.ready(plan['stage'])):
                    raise TeachingError('This Squid acquisition has not completed. Pickup blocked.')
                at_position(self.stage.command('get_position',{}),self.stage.saved()['dropoff'])
            try:
                run.claim(token);record['status']='running';save()
                execute_job('Wait for imaging and return Squid to loading',
                            lambda r:self.stage.execute(r,plan['stage'],publish_progress=False))
                done.extend(s['label'] for s in plan['stage']['steps'])
                check();self.stage.arm_clear();loading_ready()
                self.backend.verify_confirmation(plan['retrieval'],prepared=True)
                for step in plan['retrieval']['steps']:
                    loading_ready()
                    execute_job(step['label'],lambda r,s=step:self.backend.execute_step(r,s,plan['retrieval']))
                    done.append(step['label'])
                self.stage.arm_clear()
                result=dict(active=False,ok=True,done=done,step=None,error='',message='Plate retrieved from Squid and returned Home.')
                record['status']='completed'
            except Exception as error:
                record['status']='stopped_or_failed'
                result=dict(active=False,ok=False,done=done,step=self.agent.run_state.get('step'),error=str(error),message='Squid retrieval stopped: '+str(error))
            finally:
                try:
                    record['result']=result;save()
                except Exception as error:
                    result=dict(active=False,ok=False,done=done,error=str(error),message='Retrieval ended but its result could not be saved. Review before another run.')
                with self.agent.lock:self.agent.run_state=result
                self.agent._say('lacry',result['message'])
                run.release(token)
        self.thread=threading.Thread(target=worker,daemon=True,name='squid-retrieval')
        try:self.thread.start()
        except Exception:
            run.release(token);record['status']='not_started';save()
            with self.agent.lock:self.agent.run_state.update(active=False,ok=False,message='Retrieval did not start.')
            raise
        return dict(ok=True,message='Tracking this acquisition. I will return Squid to loading and bring the plate Home after it finishes; no further Yes is needed.')
