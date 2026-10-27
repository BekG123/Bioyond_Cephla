"""Local Hamilton bridge contract; no vendor API or completion is invented."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse
from uuid import uuid4
from researcher_teaching import TeachingError

CONFIG = Path(__file__).resolve().parent/'hamilton_connection.json'


class HamiltonAdapter:
    def __init__(self, config=CONFIG, request=None, sleep=time.sleep):
        self.config, self.request, self.sleep = Path(config), request, sleep

    def settings(self):
        data=json.loads(self.config.read_text(encoding='utf-8-sig'))
        if data.get('enabled') is not True:
            raise TeachingError('Hamilton start/finished connection: Coming Soon. Configure the local bridge before running this experiment.')
        url=urlparse(data.get('base_url',''))
        if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password:
            raise TeachingError('Hamilton bridge must use a configured local HTTP address without embedded credentials.')
        return data

    def call(self, method, path, body=None):
        cfg=self.settings()
        if self.request:
            result=self.request(method,path,body)
        else:
            req=Request(cfg['base_url'].rstrip('/')+path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json'},method=method)
            with urlopen(req,timeout=5) as response:
                result=json.loads(response.read(100000))
        if not isinstance(result,dict) or result.get('ok') is not True:
            raise TeachingError('Hamilton did not acknowledge the bridge request.')
        return result

    def status(self):
        try:
            value=self.call('GET','/status')
            if not isinstance(value.get('session_id'),str) or not value['session_id']:
                raise TeachingError('Hamilton bridge has no session identity.')
            if value.get('simulation') is not False:
                raise TeachingError('This Hamilton workflow requires a physical instrument connection.')
            return dict(value,available=True,connected=True,message='Hamilton bridge connected.')
        except Exception as error:
            return dict(available=False,connected=False,message=str(error))

    def deploy(self):
        state=self.status()
        if not state['available']:raise TeachingError(state['message'])
        return state

    def prepare(self,protocol):
        state=self.deploy()
        if not isinstance(protocol,str) or not protocol.strip() or protocol not in state.get('protocols',[]):
            raise TeachingError('Choose a protocol reported by the connected Hamilton bridge.')
        if state.get('state')!='idle' or state.get('ready_for_robot') is not True:
            raise TeachingError('Hamilton must be idle and ready for robot access before starting.')
        timeout=self.settings().get('timeout_s',86400)
        if type(timeout) not in (int,float) or not 1<=timeout<=86400:
            raise TeachingError('Invalid Hamilton wait timeout.')
        return dict(protocol=protocol,session_id=state['session_id'],settings_hash=self.settings_hash(),timeout_s=timeout)

    def settings_hash(self):
        return hashlib.sha256(json.dumps(self.settings(),sort_keys=True).encode()).hexdigest()

    def verify(self,plan,robot_access=False):
        state=self.deploy()
        if self.settings_hash()!=plan['settings_hash'] or state['session_id']!=plan['session_id']:
            raise TeachingError('Hamilton session or connection settings changed. Request a new plan.')
        if state.get('state') not in ('idle','running','completed'):
            raise TeachingError('Hamilton reports a fault or uncertain state.')
        if robot_access and (state.get('ready_for_robot') is not True or state.get('state') not in ('idle','completed')):
            raise TeachingError('Hamilton has not confirmed safe robot access.')
        return state

    def start(self,plan,plate_id,save):
        state=self.verify(plan)
        if state.get('state') not in ('idle','completed'):
            raise TeachingError('Hamilton is already running; no new start was sent.')
        ticket=dict(request_id=uuid4().hex,plate_id=plate_id,protocol=plan['protocol'],
                    session_id=plan['session_id'],status='start_requested')
        save(deepcopy(ticket))
        try:
            result=self.call('POST','/jobs',ticket)
            if any(result.get(k)!=ticket[k] for k in ('request_id','plate_id','protocol','session_id')) or not result.get('job_id'):
                raise TeachingError('Hamilton start acknowledgement does not match this plate/request.')
            ticket.update(job_id=result['job_id'],status='running');save(deepcopy(ticket))
            return ticket
        except Exception:
            ticket['status']='uncertain';save(deepcopy(ticket));raise

    def wait(self,plan,ticket,save,stopped,progress):
        deadline=time.monotonic()+plan['timeout_s']
        while time.monotonic()<deadline:
            if stopped():raise TeachingError('Workflow stopped while Hamilton was running. Check the instrument; no automatic reset or retry was sent.')
            self.verify(plan)
            result=self.call('GET','/jobs/'+quote(ticket['job_id'],safe=''))
            if any(result.get(k)!=ticket[k] for k in ('job_id','request_id','plate_id','protocol','session_id')):
                raise TeachingError('Hamilton status belongs to another job or plate. Pickup blocked.')
            progress(result)
            if result.get('status')=='completed' and result.get('success') is True and result.get('ready_for_robot') is True:
                ticket['status']='completed';save(deepcopy(ticket));return dict(ok=True,job_id=ticket['job_id'])
            if result.get('status') not in ('queued','running'):
                raise TeachingError('Hamilton job failed, stopped or has uncertain completion. Pickup blocked.')
            self.sleep(.5)
        raise TeachingError('Hamilton completion timed out. Pickup blocked.')

    def start_cycle(self,protocol,plate_id):
        raise TeachingError('Use the confirmed complete workflow so the request and job ID are recorded before starting Hamilton.')

    def completed_for_pickup(self,plan,ticket):
        state=self.verify(plan,robot_access=True)
        result=self.call('GET','/jobs/'+quote(ticket['job_id'],safe=''))
        if state.get('job_id')!=ticket['job_id'] or any(result.get(k)!=ticket[k] for k in ('job_id','request_id','plate_id','protocol','session_id')):
            raise TeachingError('Hamilton job identity changed before pickup.')
        if result.get('status')!='completed' or result.get('success') is not True or result.get('ready_for_robot') is not True:
            raise TeachingError('Hamilton completion is no longer confirmed. Pickup blocked.')
        return result

    def wait_finished(self,job_id,stopped):
        raise TeachingError('An owned job ticket is required; use the complete workflow.')

    def stop(self,job_id):
        raise TeachingError('Hamilton abort control is not configured. Stop the instrument through its operator controls.')
