"""48-well Squid handling candidate, pending the supervised 7 mm trial.

Opening is an E1 position, not measured jaw-to-plate clearance. The earlier
5 mm opening retrieved a plate that the operator reported slipped/shifted.
"""
OPENING_MM = 7.0
GRIP_MM = 3.9
GRIP_SPEED = 5
STATUS = 'pending_supervised_7mm_opening_trial'

def settings():
    return dict(approach_opening_e1_mm=OPENING_MM,release_opening_e1_mm=OPENING_MM,
                grip_e1_mm=GRIP_MM,grip_speed=GRIP_SPEED,status=STATUS)
