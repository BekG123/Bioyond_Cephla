"""Counted experiment previews; no instrument or robot commands.

This template stays non-executable until instrument job feedback, station
pickup/release, plate supply and delivery verification are commissioned.
The model selects a recipe and count; the host owns the ordering/barriers.
"""
from researcher_teaching import TeachingError
from station_handling import station_plan

RECIPE = 'hamilton_to_squid'
BLOCKERS = [
    'Hamilton protocol start and finished signals: Coming Soon.',
    'Automatic station pickup, release and delivery confirmation: Coming Soon.',
    'Plate supply and the Squid destination must be defined for every cycle.',
]
PHASES = [
    ('plate_ready', 'Confirm the next plate and Hamilton protocol are ready'),
    ('home_before_dispense', 'Park the arm at Home and confirm arrival'),
    ('start_dispense', 'Start Hamilton dispensing and save its job ID'),
    ('wait_dispense', 'Wait at Home until Hamilton confirms this job finished'),
    ('pickup', 'Go Home → Hamilton and pick up the finished plate'),
    ('transfer', 'Carry the plate Hamilton → Home → Squid'),
    ('verify_delivery', 'Place the plate and confirm delivery at Squid'),
    ('return_home', 'Return Squid → Home before the next cycle'),
]


def build_experiment(recipe, repetitions, protocol=''):
    if recipe != RECIPE:
        raise TeachingError('Specify a supported experiment; do not guess its steps.', 400)
    if type(repetitions) is not int or not 1 <= repetitions <= 100:
        raise TeachingError('Choose a whole number of cycles from 1 to 100.', 400)
    if not isinstance(protocol,str) or len(protocol)>200:
        raise TeachingError('Provide a short Hamilton protocol name.', 400)
    steps=[]
    for cycle in range(1,repetitions+1):
        for phase,label in PHASES:
            steps.append(dict(kind='experiment_preview',phase=phase,cycle=cycle,
                              label=f'Cycle {cycle}/{repetitions}: {label}'))
            if phase=='pickup':
                steps[-1]['station_handling']=station_plan('Hamilton','pickup')
            elif phase=='verify_delivery':
                steps[-1]['station_handling']=station_plan('Squid','release')
            if 'station_handling' in steps[-1]:
                # The following transfer/return phase owns departure; do not
                # include a second Home trip inside the local handling step.
                steps[-1]['station_handling']['steps']=steps[-1]['station_handling']['steps'][:-1]
                steps[-1]['station_handling']['departure']='Following travel phase uses the existing Home route.'
    blockers=list(BLOCKERS)
    if not protocol.strip():
        blockers.append('Select the Hamilton dispensing protocol before execution.')
    return dict(dispatch='experiment_preview',executable=False,recipe=recipe,
        repetitions=repetitions,protocol=protocol.strip(),actions=[],
        labels=[f'Hamilton dispensing and Squid transfer × {repetitions}'],
        summary=f'{repetitions} cycles: dispense while waiting at Home, then transfer Hamilton → Home → Squid and return Home.',
        steps=steps,blockers=blockers,requirements=[
            'Preview only. Confirm the complete experiment before any hardware starts.',
            'Each cycle must finish and its delivery be confirmed before the next starts.',
            'Any failure, lost completion signal or uncertain result stops the run; no automatic retry.'],
        completion_policy=dict(wait_station='Home',job_id_match_required=True,
            elapsed_time_is_not_completion=True,next_cycle_requires_delivery=True,
            on_failure='stop_and_ask',automatic_retry=False))
