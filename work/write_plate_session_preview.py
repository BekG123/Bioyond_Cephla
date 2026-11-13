"""Save the selected Hamilton preparation plan; never connects to hardware."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'operator_ui'))
from plate_session import configuration, preview

config = configuration()
plan = preview(config['selected_supervised_trial_destination'],
               dict(calibrated=False, reason='Offline preparation; no live session receipt asserted.'))
plan['motion_started'] = False
plan['hardware_observations'] = None
folder = ROOT/'operator_ui/reports/plate_session'
folder.mkdir(parents=True, exist_ok=True)
path = folder/'hamilton_home_idle_preview_20261110_review01.json'
with path.open('x', encoding='utf-8') as stream:
    json.dump(plan, stream, indent=2)
print(path)
