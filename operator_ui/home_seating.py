"""One continuous HOME seating descent; never changes pickup geometry.

Operator requested 1 mm lower at speed 5 on both station returns, 2026-11-11.
Physical seating acceptance for this adjustment remains pending.
"""


def seating_plan(pickup_pose):
    return dict(pose=dict(pickup_pose,Z=round(pickup_pose['Z']-1.0,3)),
                lower_mm=1.0,speed=5,mode='continuous_descent_v2')
