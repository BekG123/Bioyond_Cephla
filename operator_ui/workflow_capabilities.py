"""Declarative workflow contracts, composed by state rather than ordered tuples.

The model selects operations/goals. Only host-registered executors may bind
contracts to commands; neither model text nor a success log imports Python.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from researcher_teaching import TeachingError

MANIFEST = Path(__file__).with_name('workflow_capabilities.json')


def load():
    raw = MANIFEST.read_bytes()
    data = json.loads(raw)
    if data.get('schema_version') != 1:
        raise TeachingError('Unsupported workflow capability registry version.')
    ids = [item['id'] for item in data['capabilities']]
    if len(ids) != len(set(ids)):
        raise TeachingError('Duplicate workflow capability ID.')
    return data, hashlib.sha256(raw).hexdigest()


def operations(executor=None):
    data, _ = load()
    return {c['operation'] for c in data['capabilities'] if executor is None or c['executor']==executor} | set(data['goals'])


def matches(state, required):
    return all(state.get(key) == value for key, value in required.items())


def compose(requested, state, profile, cycles=1, *, registry=None):
    """Consume every requested action/goal; never return an executable prefix.

An explicit action requires its actual starting state. A goal may already be
satisfied by the preceding capability (retrieval includes HOME release), or
be fulfilled by one registered capability with matching preconditions.
"""
    data = registry if registry is not None else load()[0]
    if not isinstance(requested, list) or not 1 <= len(requested) <= 20 or type(cycles) is not int or not 1 <= cycles <= 20:
        raise TeachingError('Choose 1–20 operations and 1–20 cycles.')
    available = [c for c in data['capabilities'] if c['profile'] == profile]
    current = deepcopy(state)
    chosen, trace = [], []
    for cycle in range(1, cycles + 1):
        for operation in requested:
            goal = data['goals'].get(operation)
            if goal and matches(current, goal):
                trace.append(dict(operation=operation, cycle=cycle, satisfied_by='verified_postcondition', state=deepcopy(current)))
                continue
            candidates = [c for c in available if matches(current, c['requires']) and
                          (matches(dict(current, **c['effects']), goal) if goal else c['operation'] == operation)]
            if len(candidates) != 1:
                declared = [c for c in available if c['operation'] == operation]
                requirements = [c['requires'] for c in declared]
                raise TeachingError(f"Cannot compose operation {operation!r} in cycle {cycle}: "
                    f"current state {current}; required {requirements or goal or 'a registered executor for this profile'}. "
                    'The complete requested plan is retained; nothing started.')
            capability = deepcopy(candidates[0])
            chosen.append(dict(capability=capability, cycle=cycle, requested_operation=operation))
            current.update(capability['effects'])
            trace.append(dict(operation=operation, cycle=cycle, capability=capability['id'], state=deepcopy(current)))
    return dict(capabilities=chosen, trace=trace, final=current)


def catalog():
    data, digest = load()
    return dict(schema_version=data['schema_version'], sha256=digest, capabilities=data['capabilities'], goals=data['goals'],
        planning='Match declared preconditions and postconditions; no whitelist of complete operation orders.',
        evidence='Executors independently verify accepted route hashes, fresh predecessor receipts, plate identity and live state.',
        scope='Registered plate handling, registration and instrument operations. The workflow tool index also discovers every installed planner, including standalone workflows. Archived trials are evidence, not executable registrations.')


def compose_hotel(requested, profile, slot, *, registry=None):
    if not requested or requested[0]!='retrieve_hotel':
        raise TeachingError('A hotel source requires retrieve_hotel as the first operation.')
    return compose_ordered(requested,dict(plate_location='hotel',payload='empty',arm_location='HOME',registered=False),
                           profile,slot=slot,registry=registry)


def compose_ordered(requested, state, profile, *, slot=None, registry=None):
    """Resolve ordered operations using contracts and bounded transport prerequisites.

    Only declared preparation capabilities may be inserted. Instrument jobs and
    hotel retrieval never run as implicit prerequisites. The full expanded plan
    is bound before any dispatch; final custody comes from the resulting state.
    """
    from collections import deque
    data = registry if registry is not None else load()[0]
    available = [c for c in data['capabilities'] if c['profile']==profile and
                 ('slots' not in c or slot in c['slots'])]
    if not isinstance(requested,list) or not 1<=len(requested)<=20:
        raise TeachingError('Choose 1–20 ordered workflow operations.')
    current = deepcopy(state)
    chosen, trace = [], []
    def apply(cap, operation, inserted=False):
        current.update(cap['effects'])
        chosen.append(dict(capability=deepcopy(cap), requested_operation=operation, inserted=inserted))
        trace.append(dict(operation=operation, capability=cap['id'], inserted=inserted, state=deepcopy(current)))
    for operation in requested:
        goal = data['goals'].get(operation)
        if goal and matches(current, goal):
            trace.append(dict(operation=operation, satisfied_by='verified_postcondition', state=deepcopy(current)))
            continue
        declared = [c for c in available if c['operation']==operation]
        if goal:
            declared = [c for c in available if matches(dict(current, **c['effects']), goal)]
        if not declared:
            raise TeachingError(f'{operation}: no composable executor for profile {profile}, slot {slot}. See its standalone planner in get_workflow_catalog.')
        candidates=[]
        for cap in declared:
            required=dict(cap['requires'])
            # Every outbound hotel chain must acquire a fresh barcode identity.
            if cap.get('phase')=='delivery':required['registered']=True
            queue=deque([(deepcopy(current), [])]);visited=set()
            while queue:
                state,path=queue.popleft();key=json.dumps(state,sort_keys=True)
                if key in visited:continue
                visited.add(key)
                if matches(state,required):
                    candidates.append((cap,path));break
                if not goal and not cap.get('allow_preparation'):continue
                for preparation in available:
                    if not preparation.get('auto_prepare') or preparation['id']==cap['id']:continue
                    req=dict(preparation['requires'])
                    if preparation.get('phase')=='delivery':req['registered']=True
                    if matches(state,req):
                        queue.append((dict(state,**preparation['effects']),path+[preparation]))
        if candidates:
            shortest=min(len(path) for _,path in candidates)
            candidates=[(cap,path) for cap,path in candidates if len(path)==shortest]
        if len(candidates)!=1:
            raise TeachingError(f'{operation}: current state {current}; requires {[c["requires"] for c in declared]}. No unique accepted preparation path; nothing started.')
        cap,path=candidates[0]
        for preparation in path:apply(preparation,preparation['operation'],True)
        apply(cap,operation)
    return dict(capabilities=chosen,trace=trace,final=current,requested_operations=list(requested))
