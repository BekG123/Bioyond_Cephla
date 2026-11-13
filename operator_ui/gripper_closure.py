"""Two-speed arm E1 closure; no hardware I/O or endpoint selection.

The published HostPoint type 3 executes one MoveExtJ, followed by MOVFINISH.
Callers retain their own preflight, fault, arrival and payload checks. This is
not the XYZ trajectory queue and does not change diagnostic increment tests.
"""
import math

POLICY = 'approach10_final1mm_speed5_v2'
SPEED = 5
APPROACH_SPEED = 10
FINAL_DISTANCE_MM = 1.0
GRIP_ABOVE_TARGET_MM = 0.2


def grip_feedback_matches(actual, target, *, lower_tolerance=0.07):
    """Accepted closing feedback: existing inward bound, +0.2mm outward.

    Position acceptance alone does not establish plate retention. Opening
    commands keep their separate, tighter checks.
    """
    if any(type(v) not in (int,float) or not math.isfinite(v)
           for v in (actual,target,lower_tolerance)) or lower_tolerance<0:
        return False
    return target-lower_tolerance-1e-9 <= actual <= target+GRIP_ABOVE_TARGET_MM+1e-9


def closure_plan(start_mm, target_mm):
    """Approach to target+1 at10, then the final millimeter at5.

Each command finishes before the next starts: the controller must decelerate
at the boundary. Callers verify completion before dispatching the slow finish.
If already within the final millimeter, the entire remaining move is at5.
"""
    if any(type(v) not in (int, float) or not math.isfinite(v)
           for v in (start_mm, target_mm)):
        raise ValueError('Finite E1 start and target required.')
    if not 0 <= target_mm <= start_mm <= 28.05:
        raise ValueError('E1 closure must stay within 0..28.05 mm and close inward.')
    boundary = round(target_mm+FINAL_DISTANCE_MM, 10)
    commands = []
    current = start_mm
    if current > boundary:
        commands.append(dict(from_e1_mm=current, target_e1_mm=boundary,
                             delta_mm=current-boundary, speed=APPROACH_SPEED,
                             phase='approach'))
        current = boundary
    commands.append(dict(from_e1_mm=current, target_e1_mm=target_mm,
                         delta_mm=current-target_mm, speed=SPEED, phase='finish'))
    return dict(closure_policy=POLICY, start_e1_mm=start_mm,
                target_e1_mm=target_mm, commands=commands, command_count=len(commands),
                approach_speed=APPROACH_SPEED, final_speed=SPEED,
                final_distance_mm=FINAL_DISTANCE_MM,
                dispatch=False)


def closing_targets(start_mm, target_mm):
    return [c['target_e1_mm'] for c in closure_plan(start_mm, target_mm)['commands']]


def closure_commands(start_mm, target_mm):
    return closure_plan(start_mm, target_mm)['commands']
