"""Compose existing station routines into one confirmed plan; never start motion."""
from copy import copy, deepcopy

from autonomy import check_path
from researcher_teaching import TeachingError
from scope_step_trial import near
from squid_handling import plan as handling_plan


ALIASES = {
    'retrieve_hamilton_to_squid': ['hamilton_retrieve', 'move_scope'],
    'deliver_hamilton_to_squid': ['hamilton_retrieve', 'squid_dropoff'],
}
SEQUENCES = tuple(ALIASES.values())


def projected_home(backend, pickup):
    """Derive the next planning state from the checked pickup's final route.

    This state is only used to compile the second phase. Execution still checks
    the real pose, joints, jaws and evidence before every step.
    """
    leg = pickup['steps'][-1]
    pose, joints = deepcopy(leg['start']), deepcopy(leg['joints'])
    offset = joints['J1'] - pose['Z']
    envelope = backend.travel_envelope(pose, leg['points'], leg['profile'])
    for target in leg['points']:
        joints = check_path(pose, target, joints, backend.params(), envelope)
        joints['J1'] = target['Z'] + offset
        pose = deepcopy(target)
    return dict(pose_mm=pose, joints=joints, external_axes={'E1': 3.7})


def plan(backend, actions):
    sequence = ALIASES.get(actions[0], actions) if len(actions) == 1 else actions
    if sequence not in SEQUENCES:
        raise TeachingError('This station combination is not implemented. Request the complete supported transfer.')
    first = handling_plan(backend, 'hamilton_retrieve')
    predicted = projected_home(backend, first)
    # Isolated planning view; never changes the real service or its status.
    view = copy(backend)
    view.healthy = lambda *args, **kwargs: deepcopy(predicted)
    if sequence[1] == 'squid_dropoff':
        second = handling_plan(view, 'squid_dropoff')
        summary = 'Retrieve the plate from Hamilton, travel via Home, leave it at Squid, then return Home empty.'
    else:
        second = view.compile(['move_scope'])
        second['prepare'] = False
        summary = 'Retrieve the plate from Hamilton, travel via Home to Squid, and keep the plate held.'
    phases = [first, second]
    steps = []
    for index, phase in enumerate(phases):
        for step in phase['steps']:
            steps.append({**deepcopy(step), 'transfer_phase': index})
    result = {k: deepcopy(first[k]) for k in ('start', 'joints', 'e1', 'cfg', 'envelope')}
    result.update(dispatch='station_transfer', actions=list(actions), phases=phases,
                  steps=steps, prepare=False, executable=True, supervised_trial=True,
                  camera_required=False, summary=summary,
                  requirements=list(dict.fromkeys(first['requirements'] + second['requirements'])))
    # The second phase starts with the plate acquired in the first phase;
    # requirements describe that checkpoint rather than claiming it is held now.
    result['requirements'] = [
        text.replace('The plate is securely held; the Squid holder',
                     'After the Hamilton pickup, the plate must be securely held; the Squid holder')
        for text in result['requirements']
    ]
    return result


def verify(backend, proposed):
    current = plan(backend, proposed['actions'])
    for key in ('cfg', 'envelope', 'dispatch', 'prepare', 'executable'):
        if current[key] != proposed.get(key):
            raise TeachingError('The complete transfer plan changed. Request a fresh plan.')
    if len(current['phases']) != len(proposed.get('phases', [])):
        raise TeachingError('Transfer phases changed.')
    for expected, actual in zip(current['phases'], proposed['phases']):
        for key in ('actions', 'cfg', 'envelope', 'dispatch', 'handling_evidence', 'prepare'):
            if expected.get(key) != actual.get(key):
                raise TeachingError('Transfer phase settings changed.')
        near(expected['start'], actual['start'], .2)
        if abs(expected['e1']-actual['e1']) > .05:
            raise TeachingError('Transfer gripper changed.')
        if len(expected['steps']) != len(actual['steps']):
            raise TeachingError('Transfer phase steps changed.')
        for left, right in zip(expected['steps'], actual['steps']):
            near(left['start'], right['start'], .2)
            if any(abs(left['joints'][key]-right['joints'][key]) > .5
                   for key in ('J1','J2','J3','J4')):
                raise TeachingError('Transfer joint configuration changed.')
            for key in ('kind','points','profile','sources','expected_e1',
                        'target_e1','speed','review_label'):
                if left.get(key) != right.get(key):
                    raise TeachingError('Transfer phase steps changed.')
    flattened = [{**deepcopy(step), 'transfer_phase': index}
                 for index, phase in enumerate(proposed['phases'])
                 for step in phase['steps']]
    if flattened != proposed['steps']:
        raise TeachingError('Transfer execution order changed.')


def execute_step(backend, run, step, proposed):
    index = step.get('transfer_phase')
    if type(index) is not int or not 0 <= index < len(proposed['phases']):
        raise TeachingError('Transfer phase is unavailable.')
    local = {k: deepcopy(v) for k, v in step.items() if k != 'transfer_phase'}
    phase = proposed['phases'][index]
    if local not in phase['steps']:
        raise TeachingError('Transfer step differs from the confirmed phase.')
    return backend.execute_step(run, local, phase)
