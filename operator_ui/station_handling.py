"""Static experiment previews; live station operations use squid_handling.py."""
from researcher_teaching import TeachingError
import json
from pathlib import Path

PROFILE = Path(__file__).resolve().parents[1]/'Pick and Hold/Station Handling/pickup_dropoff_profile.json'

RULES = '''
At Hamilton or Squid, NEVER use Full Calibration, plate_calibration, align,
descend or grip from the camera/two-disk workflow to load or unload a plate.

Those actions belong only at the calibration disk station of the arm at the very beginning
of the workflow. Do not repeat two-disk calibration at instrument stations or
on every transfer/repetition unless the researcher explicitly requests a new
calibration at that calibration station.

Squid handling is now physically tested and executable through
plan_station_handling(station="Squid", operation="release" or "pickup"):
- Both routines can start at Home OR already seated at the exact taught Squid
  loading pose and finish at Home. From Squid, skip the outbound travel;
  do not ask the researcher to return Home just to come back again.
  Transit/return are137, final Squid approach descent10, local lift5.
- Release carries the securely held plate to Squid, opens E1 to 5 mm at speed 5,
  lifts the empty jaws 5 mm at speed 5, and returns Home empty.
- Pickup travels with empty jaws at E1=5 mm to the taught Squid pose, closes to
  E1=3.7 mm at speed 5, lifts the plate 5 mm at speed 5, and returns Home.
- Use squid_dropoff or squid_retrieve via propose_actions for the same routines.
- Ask for the usual single confirmation of the full routine. A chat Yes starts it.
- The Squid stage/holder must be in the taught loading position. The researcher
  must confirm the plate/payload state and clearance; joint readings do not see it.
- When releasing from the seated Squid pose, confirm the plate is flat and fully
  supported before opening. Being near Squid or 5mm above it is not seated.
- Squid status monitoring is read-only; these standalone handling routines never start imaging.
  Do not infer completion from idle state or an old/historical record.
  Outside a confirmed plan_squid_experiment workflow, retrieval requires explicit operator authorization after completion or for an
  explicitly hypothetical completion test. Do not automatically retrieve just
  because drop-off finished or a guessed amount of time elapsed.
- No two-disk calibration at Squid. Do not replace release with move_scope alone:
  move_scope is travel only and does not leave the plate or return Home.
Hamilton uses the same sequence via plan_station_handling(Hamilton, release/pickup)
or hamilton_dropoff/hamilton_retrieve, as an executable SUPERVISED TRIAL:
- Start at Home with the plate held at E1=3.7 for drop-off, or empty jaws at
  E1=5 for retrieval. Travel137 to the current taught Hamilton endpoint supplied
  by the host. The accepted 26 October revision replaces the old lower endpoint;
  both travel directions pass through true Home. Do not invent coordinates.
- Pause for researcher inspection of plate support/alignment before jaw motion.
- Drop-off opens to5 at speed5; retrieval closes to3.7 at speed5.
- Lift5mm vertically at speed5. Pause for inspection: plate stays seated for
  drop-off, or plate lifts evenly without slipping for retrieval.
- Return along the taught Hamilton->true Home route at137. No Home-area detour.
- Do not add backward jogs or camera calibration. Do not claim Hamilton loaded
  handling is commissioned from Squid trials or empty Hamilton travel.
- Hamilton is connected through the Prep API. Standalone plate retrieval still
  requires explicit completion authorization; this routine does not start or
  wait for an instrument operation. Never guess completion from old logs.
The plan requires already-running Auto; do not restart with a plate held.
For "go back to Hamilton, take the plate, and bring it to Squid" starting at Home,
use propose_actions(["retrieve_hamilton_to_squid"]). It chains Hamilton retrieval
and onward Home->Squid travel into ONE plan and leaves the plate held at Squid.
If the researcher explicitly requests leaving/dropping it at Squid, use
propose_actions(["deliver_hamilton_to_squid"]); this adds Squid release and
empty return Home. Both retain the Hamilton inspection checkpoints and stop
on any failure. Never propose only hamilton_retrieve for these compound requests.
If already at Hamilton holding the plate, transfer_hamilton_squid is the existing
travel-only route via Home. Do not add pickup, release, or imaging implicitly.
Multi-cycle instrument experiments remain previews until integration is ready.
A transport-only rehearsal keeps the jaws unchanged.
'''


def station_plan(station,operation):
    if station not in ('Hamilton','Squid') or operation not in ('pickup','release'):
        raise TeachingError('Choose pickup or release at Hamilton or Squid.',400)
    profile=json.loads(PROFILE.read_bytes())
    opening=5
    if operation=='release':
        labels=[f'Confirm the plate is supported at {station}',
                f'Open the jaws to E1={opening:g} mm at speed 5',
                'Confirm the jaws are clear and the plate remains supported',
                'Lift the empty jaws 5 mm at speed 5 within the verified station headroom',
                f'Follow the taught {station} → Home route']
    else:
        labels=[f'Use the taught approach just above the plate at {station}, within its headroom',
                f'Lower the jaws, open to E1={opening:g} mm, to the taught gripping height',
                'Close to E1=3.7 mm at speed 5',
                'Lift the plate 5 mm at speed 5 within the verified station headroom',
                f'Follow the taught {station} → Home route']
    return dict(dispatch='station_handling_preview',executable=False,actions=[],
        station=station,operation=operation,camera_required=False,
        grip_target_e1_mm=profile['pickup_e1_mm'] if operation=='pickup' else None,
        opening_e1_mm=opening,release_speed=profile['jaw_speed'],approach_clearance_mm=None,
        lift_mm=profile['lift_mm'],lift_speed=profile['lift_speed'],
        departure_speed=profile['departure_translation_speed'],
        validation_status=('operator_accepted_squid' if station=='Squid' else profile['status']),
        validated_location=('Squid' if station=='Squid' else profile['validated_location']),
        labels=[f'{operation.title()} at {station}'],
        summary=f'{operation.title()} at {station} using its taught pose, then return Home. No camera calibration.',
        steps=[dict(kind='station_handling_preview',label=label) for label in labels],
        requirements=['Plate support, jaw clearance and the loaded departure must be verified.'],
        blockers=([f'Use the live supervised {station} handling planner to test support height, 5 mm jaw setting, lift headroom and departure.']
                  if station=='Hamilton' else ['Use the live Squid handling planner from Home or the taught seated Squid pose to check readiness and propose execution.']))
