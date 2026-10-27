"""Refresh Hamilton's camera/TCP readings and create a read-only alignment preview."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]))
from hamilton_dynamic_alignment import alignment_preview
from probe_prep_coordinates import main as capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-dir',type=Path,help='Reprocess an existing capture instead of reading hardware.')
    parser.add_argument('--registration',type=Path,help='Physically verified reference-point registration, if available.')
    args = parser.parse_args()
    folder = args.capture_dir or capture(['--capture'])
    subprocess.run([sys.executable,'-B',str(ROOT/'estimate_tip_plane.py'),'--root',str(folder)],
                   check=True,capture_output=True,text=True)
    estimate = json.loads((folder/'tip_plane_estimate.json').read_text())
    probe = json.loads((folder/'probe.json').read_text())
    registration = json.loads(args.registration.read_text()) if args.registration else None
    preview = alignment_preview(estimate,probe,registration)
    (folder/'alignment_plan_preview.json').write_text(json.dumps(preview,indent=2),encoding='utf-8')
    print(json.dumps({'capture_directory':str(folder),'tip_rims_detected':estimate['tip_rims_used'],
        'preview_image':str(folder/'alignment_preview.png'),'preview':preview},indent=2))


if __name__ == '__main__':
    main()
