"""HTTP adapter for one-queue travel through the existing Flask hardware owner."""
import time
from uuid import uuid4
from proof_lift_plate import api,near,write
from squid_single_queue import validate_route
from squid_handling_route import CURRENT_SHA

def preview(route,speeds):
    _,expected=validate_route(route[0],route[1:])
    if list(speeds)!=expected:raise RuntimeError('Queued Squid speeds changed')
    body=dict(ready=True,direction='forward' if expected[0]==137 else 'reverse',
              trial_id='squid_'+uuid4().hex,candidate_sha256=CURRENT_SHA)
    result=api('developer/api/squid-queue/preview',body)
    if not result.get('ok'):raise RuntimeError(str(result))
    for key,value in [('speeds',expected),('source_sha256',CURRENT_SHA),('protocol',220109)]:
        if result.get('plan',{}).get(key)!=value:raise RuntimeError('Unexpected Squid queue preview')
    near(result['plan']['start'],route[0],.05)
    near(result['plan']['points'][-1],route[-1],.02)
    return body,result

def execute(body,plan,route,baseline,source_state,output,plan_path,plan_sha):
    record=dict(status='started',at=time.time(),plan=str(plan_path),plan_sha256=plan_sha,
        route=route,speeds=plan['leg_speeds'],source_state=source_state,samples=[],steps=[],
        authorization=plan.get('operator_intent'),preserved_e1_mm=baseline,
        gripper_commands=[],startup_commands=[],release_executed=False,executor='lua_queue_segment_speeds')
    write(output,record)
    try:
        response=api('developer/api/squid-queue/start',body);record['dispatch']=response;write(output,record)
        if not response.get('ok'):raise RuntimeError('Squid queue start refused')
        deadline=time.monotonic()+180
        while True:
            q=api('seq');s=api('state');r=s['robot'];record['samples'].append(s)
            if (q.get('name')!='squid_single_queue' or not r.get('connected') or not r.get('ok') or r.get('errors')
                or not r.get('enabled') or r['program_state']['state']!='running'
                or r['control_mode']['mode']!='auto' or abs(r['external_axes']['E1']-baseline)>.1):
                raise RuntimeError('Squid queue feedback uncertain')
            if not q['active']:
                result=q.get('result') or {}
                if not result.get('ok') or result.get('segment_speeds')!=plan['leg_speeds'] or result.get('completion_barriers')!=1:
                    raise RuntimeError('Squid queue completion unverified')
                near(r['pose_mm'],route[-1],.1)
                record.update(status=plan.get('completion_status','queued_travel_completed_pending_operator_assessment'),
                              final_state=s,queue_result=result)
                # The final barrier confirms queue completion; no invented per-point arrival samples.
                record['steps']=[dict(target=p,speed=v,status='completed_in_queue') for p,v in zip(route[1:],plan['leg_speeds'])]
                break
            if time.monotonic()>deadline:raise RuntimeError('Squid queue timed out')
            time.sleep(.2)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:
            record['sequence_stop']=api('seq/stop',{})
            record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(output,record)
    return record
