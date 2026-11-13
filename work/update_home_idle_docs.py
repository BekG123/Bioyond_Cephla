"""Apply the approved naming note without rewriting historical evidence."""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
MARKER = b'## HOME / IDLE location contract (2026-11-10)'
NOTE = '''## HOME / IDLE location contract (2026-11-10)

IDLE is the former true Home at X289.97/Y62.63/Z248.02/Rz-3.88. HOME now
means the calibration holder, with separate seating, clearance and grip poses.
Historical coordinates, controller route keys and trial hashes stay unchanged:
in the legacy procedures below, Home means IDLE unless explicitly marked HOME
holder. The old Home-area remains a distinct historical waypoint.

For a new experiment, use `operator_ui/plate_session.py` and
`Pick and Hold/plate_session_workflow.json`: full calibration once per valid
session -> IDLE holding the plate -> HOME seated -> verify support -> release
-> lift 5 mm at speed 5 -> open E1 to 28 mm -> verify the full holder/plate/jaw
sweep -> orient -> verify three fresh E2 readings -> re-grip -> proof lift
-> accepted destination route. Never rotate a held plate. The new near-holder
rotation is prepared, NOT yet physically commissioned; the old rotation trial
was with the arm away at IDLE. Do not substitute it as clearance evidence.

Hamilton first (selected for the next supervised trial): absolute E2 target
90.71661229181757 degrees (90.717 displayed), tolerance 0.1 degree, using the
accepted short-side E1=25 mm profile. Positive E2 from the original orientation
was observed counterclockwise from above. Do not command current E2 plus 90.
Squid first: no rotation, verify E2 around 1.77 degrees using the existing rule
`round(E2, 3) >= 1.769 and E2 <= 1.82`, and use the accepted 48-well long-side
grip. A wrong original angle requires review, not a blind no-op or re-grip.

Lacry chat uses `move_idle` for old parking and `move_home` for the new holder
preparation preview. `/researcher/api/lacry/button/move_idle` selects old
parking. Legacy developer planner `propose(['move_home'])`, controller job names
and archived scripts still refer to IDLE; do not change their recorded poses.
The new preview API is POST `/researcher/api/lacry/plate-session/plan` with
`{"first_destination":"Hamilton"}` or `"Squid"`. It is not executable until
the new released-plate placement/clearance/re-grip connection is reviewed.
Do not claim it ran or bypass the preview with old compound station travel.

Session reuse is tied to completed full calibration plus setup fingerprints.
Restart, fault/disconnection, hand-guiding, changed references or uncertain
motion invalidate reuse; physical fixture changes must also be reported.
Keep the E-stop supervised, envelope/IK and payload checks, and stop on faults,
uncertain grip/position or timeout. No automatic retries or controller restart
with a held plate. No existing trajectory was requalified by this name change.

'''.encode('ascii')


def add_note(path, skill=False):
    raw = path.read_bytes()
    if skill:
        raw = re.sub(br'(?m)^description: ([^\r\n]+)',
                     lambda m: b'description: '+m[1].replace(b'Home', b'IDLE (former Home)'), raw, count=1) if b'IDLE (former Home)' not in raw.split(b'---',2)[1] else raw
        if raw != path.read_bytes():
            path.write_bytes(raw)
    if MARKER in raw:
        return
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    note = NOTE.replace(b'\n', newline)
    if skill:
        match = re.search(br'\r?\n---(?:\r?\n|$)', raw[3:])
        if match is None:
            raise ValueError('Missing skill frontmatter: '+str(path))
        end = 3 + match.end()
        path.write_bytes(raw[:end]+newline+newline+note+raw[end:].lstrip(b'\r\n'))
    else:
        path.write_bytes(raw+newline+newline+note)
    print(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--installed-skills', action='store_true')
    args = parser.parse_args()
    names = ['full-calibration-skill-48-well-plate-v1', 'return-home-skill-v1',
             'hamilton-squid-roundtrip-v1', 'two-station-plate-handling-v1',
             'squid-dropoff-pickup-v1', 'squid-closed-claw-transfer-v1', 'trajectory-deblur']
    base = Path.home()/'.codex/skills' if args.installed_skills else ROOT/'Codex SKILLS'
    for name in names:
        add_note(base/name/'SKILL.md', skill=True)
    if not args.installed_skills:
        for path in ('README.md', 'docs/DESIGN.md', 'docs/HANDOVER_OPERATOR_UI.md'):
            add_note(ROOT/path)
        # This is an archival prompt file, not the live SYSTEM constant.
        add_note(ROOT/'operator_ui/lacry_prompt.txt')
        ui = ROOT/'operator_ui/static/lacry.html'
        raw = ui.read_bytes()
        raw = raw.replace(b'return Home.', b'return IDLE.').replace(b'Retrieve plate to Home', b'Retrieve plate to IDLE')
        raw = raw.replace(b'start and finish at Home.', b'start and finish at IDLE.')
        ui.write_bytes(raw)
