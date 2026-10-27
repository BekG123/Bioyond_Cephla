"""Offline coarse-to-fine closure proposal. No hardware dispatch or force control."""
from decimal import Decimal
import json
import math
from pathlib import Path

PROFILE = Path(__file__).with_name('fast_position_profile.json')


def plan_closure(start_mm):
    if type(start_mm) not in (int, float) or not math.isfinite(start_mm):
        raise ValueError('Finite E1 opening required.')
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    target_mm = profile['target_e1_mm']
    if (type(target_mm) not in (int, float) or target_mm not in (3.8, 3.7)
            or (target_mm == 3.7 and profile.get('supervised_trial') != 'e1_3p7_20261020')
            or profile['speed'] != 5
            or profile['phases'] != [
                dict(until_e1_mm=5.0, max_step_mm=1.0),
                dict(until_e1_mm=4.0, max_step_mm=.2),
                dict(until_e1_mm=target_mm, max_step_mm=.1)]):
        raise ValueError('Candidate geometry changed; review the planner.')
    if not target_mm <= start_mm <= 28.05:
        raise ValueError('Opening outside reviewed position range.')
    current = Decimal(str(start_mm))
    steps = []
    for phase in profile['phases']:
        floor = Decimal(str(phase['until_e1_mm']))
        increment = Decimal(str(phase['max_step_mm']))
        while current > floor:
            target = max(floor, current-increment)
            steps.append(dict(from_e1_mm=float(current), target_e1_mm=float(target),
                              delta_mm=float(current-target), speed=5))
            current = target
    return dict(start_e1_mm=start_mm, target_e1_mm=target_mm, commands=steps,
                command_count=len(steps), dispatch=False,
                validation_status='candidate_requires_supervised_validation')
