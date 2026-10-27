"""One confirmed/reserved IK Home return followed by an existing taught route."""
from copy import deepcopy
import math

from researcher_teaching import TeachingError
from scope_step_trial import near
from trajectory_queue import LuaTrajectory,travel_program_blocker

DESTINATIONS={'move_hamilton':'Hamilton','move_scope':'Squid'}


def continuation(backend,prefix,action):
    home,ident=backend.home.target()
    if prefix['home']!=home or prefix['target_id']!=ident:
        raise TeachingError('Saved Home changed. Request a fresh station plan.')
    cfg=backend.params();env={k:list(v) for k,v in backend.s.envelope.items()}
    if cfg!=prefix['cfg'] or env!=prefix['envelope']:
        raise TeachingError('Motion settings changed. Request a fresh station plan.')
    endpoint=prefix['checked'][-1]
    near(endpoint['pose'],home,.001)
    joints=deepcopy(endpoint['joints'])
    steps,_,_=backend.plan_travel(action,home,joints)
    requirements=['The taught Home-to-'+DESTINATIONS[action]+' route and station approach are clear. The gripper stays unchanged during station travel.']
    if action=='move_hamilton':
        from hamilton_true_home import candidate,requirement
        requirements.append(requirement(candidate(home,backend.s.envelope)))
    return dict(actions=[action],steps=steps,start=deepcopy(home),joints=joints,
        cfg=deepcopy(cfg),envelope=env,e1=prefix['e1'] if prefix['preserve_gripper'] else None,
        requirements=requirements,prepare=False)


def propose(agent,action):
    if action not in DESTINATIONS or agent.reviewed_home is None or agent.classic is None:
        raise TeachingError('The Home-to-station sequencer is unavailable.')
    prefix=agent.reviewed_home.propose()
    if not prefix or prefix.get('dispatch')!='ik_home_return' or not prefix.get('checked'):
        raise TeachingError('A checked IK Home connection is required for this position.')
    follow=continuation(agent.backend,prefix,action)
    state=agent.backend.healthy(automatic=True,prepared=False)
    blocker=travel_program_blocker(LuaTrajectory(agent.backend.s).capability(),
        allow_initialization=state.get('program_state',{}).get('state') in ('stopped','paused'))
    if blocker:raise TeachingError(blocker)
    return dict(dispatch='station_via_home',actions=['move_home',action],
        labels=['Return Home','Move to '+DESTINATIONS[action]],home_prefix=prefix,
        continuation=follow,destination_action=action,prepare=False,
        steps=deepcopy(prefix['steps'])+deepcopy(follow['steps']),
        requirements=prefix['requirements']+follow['requirements'],
        summary='Return Home on a checked IK route, then follow the taught route to '+DESTINATIONS[action]+'. One confirmation covers both moves.')


def start(agent,plan):
    prefix=deepcopy(plan['home_prefix']);action=plan['destination_action']
    if continuation(agent.backend,prefix,action)!=plan['continuation']:
        raise TeachingError('The station route changed. Request a fresh complete plan.')
    prefix['id']=plan['id']+':home'
    run=agent.get_runner();attempt=None;home_finished=False

    def finish_home():
        nonlocal home_finished
        if attempt is not None and not home_finished:
            agent.reviewed_home.finish(attempt,deepcopy(run.snapshot()))
            home_finished=True

    def start_home():
        nonlocal attempt
        if continuation(agent.backend,prefix,action)!=plan['continuation']:
            raise TeachingError('The station route changed before departure.')
        result,attempt=agent.reviewed_home.start(prefix)
        return {**result,'started':'researcher_home'}

    def start_destination():
        finish_home()
        if run.stopped():raise TeachingError('Stopped at Home; no station travel started.')
        follow=continuation(agent.backend,prefix,action)
        if follow!=plan['continuation']:
            raise TeachingError('The station route changed. Stopped at Home.')
        if not prefix['preserve_gripper']:
            # Approved empty-gripper preparation may close the jaws. Bind only
            # this feedback here; the approved pose/joints/path remain unchanged.
            value=agent.backend.s.external_axes().get('E1')
            if type(value) not in (float,int) or not math.isfinite(value):
                raise TeachingError('Claw feedback unavailable after Home.')
            follow['e1']=value
        agent.backend.verify_confirmation(follow,prepared=True)
        def execute(worker):
            for step in follow['steps']:
                if worker.stopped():raise TeachingError('Station travel stopped.')
                result=agent.backend.execute_step(worker,step,follow)
                if not isinstance(result,dict) or result.get('ok') is not True:
                    raise TeachingError('Station travel did not complete: '+str((result or {}).get('error','unknown result')))
            return dict(ok=True)
        return run.start('lacry_station_after_home',execute)

    def finish(final):
        finish_home()
        with agent.lock:agent.run_state=deepcopy(final)
        agent._say('lacry',final['message'])

    with agent.lock:
        if not agent.pending or agent.pending['id']!=plan['id']:
            raise TeachingError('This station plan was already used.')
        agent.pending=None
        agent.run_meta=dict(name='Home then '+DESTINATIONS[action],total_steps=2)
        agent.run_state=dict(active=True,step='Return Home',done=[],ok=None,error='',message='Returning Home before station travel.')
    try:
        agent.classic.start(include_pickup=False,tail_steps=[
            dict(label='Return Home',start=start_home),
            dict(label='Move to '+DESTINATIONS[action],start=start_destination)],
            on_finish=finish,completion_message='Arrived at '+DESTINATIONS[action]+' via Home.')
    except Exception as error:
        finish(dict(active=False,ok=False,done=[],error=str(error),message=str(error)))
        raise
    return dict(ok=True,message='Running the confirmed Home return and station travel.')
