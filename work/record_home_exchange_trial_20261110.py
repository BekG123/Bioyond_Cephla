"""Append measured HOME exchange evidence; never commands hardware."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root/'operator_ui/reports/squid_48well_approach/calibration_home_exchange_retry01_20261110'
receipt = json.loads((folder/'home_holder_release_clearance.json').read_bytes())
assert receipt['status'] == 'home_release_lift_open_completed'
assert receipt['rotation_sent'] is False
pose = receipt['final_state']['robot']['pose_mm']
e1 = receipt['final_state']['robot']['external_axes']['E1']
e2 = receipt['holder_after'][-1]['native']['external_axes']['E2']
entry = (
    '\n\n## 2026-11-10 HOME holder exchange trial\n\n'
    '- First calibration stopped before travel: E2 -1.629 deg exceeded the 2-degree correction bound. '
    'Operator restored E2 and explicitly requested the fresh retry; preserve both receipts.\n'
    '- Unchanged accepted 48-well calibration/alignment/descent, E1=3.9 grip, 5 mm proof lift '
    'and loaded IDLE return completed without faults. The reverse holder-return route passed IK/workspace checks '
    'and seated at Z73.714; operator confirmed plate fully supported and jaws clear.\n'
    '- Released to E1=7, lifted 5 mm at speed 5, then opened to 28. '
    f'Final TCP X{pose["X"]:.3f}/Y{pose["Y"]:.3f}/Z{pose["Z"]:.3f}/Rz{pose["Rz"]:.3f}; '
    f'E1={e1:.3f} mm, E2={e2:.3f} deg, no faults. No holder rotation.\n'
    '- Final visual acceptance, near-holder rotation/re-grip and automatic Lacry integration remain pending. '
    'The larger E2 restoration request needs the dedicated checked rotation path, not removal of the small-correction bound.\n'
    '- Evidence: `operator_ui/reports/squid_48well_approach/calibration_home_exchange_retry01_20261110/`. '
    'Executors: `home_exchange_holder_trial.py`, `home_exchange_clearance_trial.py`; eight offline failure-inhibition checks passed.\n'
)
path = root/'Pick and Hold/Station Handling/Observations.md'
marker = b'## 2026-11-10 HOME holder exchange trial'
if marker in path.read_bytes():
    raise RuntimeError('Observation already recorded; preserve it.')
with path.open('ab') as stream:
    stream.write(entry.encode('ascii'))
print(str(path))
