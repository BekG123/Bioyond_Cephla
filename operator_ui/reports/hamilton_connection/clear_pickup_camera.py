"""Vertically clear the camera during the authorized pickup preparation."""
import asyncio
import json
import math
import sys
from run_camera_hover_trial import capture, execute

folder = capture([])
probe = json.loads((folder / 'probe.json').read_text())
start = {int(p['channel']): [p['position_x'], p['position_y'], p['position_z']]
         for p in probe['tcp_queries']['PrepGetPositions']['positions']}
aside = '--aside' in sys.argv
expected_z = 165.5 if aside else 130
if set(start) != {1, 2} or any(abs(p[0]-46.99) > .2 or abs(p[2]-expected_z) > .2 for p in start.values()):
    raise RuntimeError('Not at the previously verified hover; no movement.')
if abs(start[1][1]-39.60) > .2 or abs(start[2][1]-66.59) > .2:
    raise RuntimeError('Channel Y changed; no movement.')
plan = {'start_positions': {str(c): p for c, p in start.items()},
        'capture_time': probe['time_utc'], 'pickup': False,
        'purpose': 'Vertical clearance for fresh camera verification during authorized pickup',
        'path': [{'phase': 'vertical_clearance', 'positions': {
            c: [p[0], p[1], p[2]+(165.5-p[2])*n/4] for c, p in start.items()}}
            for n in range(1, 5)]}
if aside:
    end = {1: [289.30, 344.99, 165.5], 2: [289.30, 365.01, 165.5]}
    count = math.ceil(max(abs(end[c][i]-start[c][i]) for c in (1,2) for i in range(3))/10)
    plan['path'] = [{'phase': 'camera_clearance_xy', 'positions': {
        c: [start[c][i]+(end[c][i]-start[c][i])*n/count for i in range(3)] for c in (1,2)}}
        for n in range(1,count+1)]
(folder / 'vertical_clearance_plan.json').write_text(json.dumps(plan, indent=2))
asyncio.run(execute(folder, plan))
print('POST-CLEARANCE CAPTURE', capture(['--capture']))
