# Lacry workflow composition

Lacry chooses ordered operations from researcher intent using
`get_workflow_catalog` and `plan_workflow`. The deterministic router chooses an
existing compound executor. It never approves or dispatches during planning.
Only a person's confirmation of the complete resulting plan starts execution.
The Researcher UI displays the full chain and any blocking qualifications.

Bindings currently available:

- Ordered Hamilton maintenance and one arm calibration: `CommandBatch`.
- Commissioned Hamilton protocol plus Squid imaging for a registered Cellvis
  plate at HOME, including existing station transfers and exact-job waits:
  `ExperimentApi`; requested cycle count and imaging selection are preserved.
- Accepted 48-well pickup/delivery/imaging/retrieval combinations:
  `AutonomousSquid`; its existing start-state and imaging checks remain active.
- Hotel retrieval to HOME: the accepted slot 1–3 executors for the 48-well
  profile. Slot 1 also accepts Cellvis P24-1.5H-N under the operator's explicit
  confirmation of prior testing, recorded in `hotel_slot1_retrieval_profiles.json`.
  Registered IDs are optional for retrieval; an unregistered plate is tracked
  by source slot and declared profile without inventing a barcode identity.

Other combinations are displayed in full as blocked. No requested operation is
silently discarded, no prefix runs, and no automatic fallback substitutes a
different profile or recipe. No new motion coordinates or controller programs
were introduced. The adapter layer is intentionally explicit: model reasoning
does not establish physical compatibility between two individually tested skills.

## Current Cellvis hotel request

Required chain: slot 1 retrieval → HOME → scanner registration → HOME → Squid
delivery/release → empty HOME return. A known barcode may be supplied as an
expected ID, but it does not replace the fresh scan. An unregistered plate can
be planned without inventing an ID. Registration must decode and save the ID;
no-read or a mismatching expected ID prevents onward delivery. No imaging or
Hamilton protocol is implicitly added to a transfer-only request.

The standalone slot 1 → HOME retrieval is executable for Cellvis24 through the
unchanged accepted executor. The operator confirmed on November 12 that the
fixed retrieval had already been tested and should be reused for this plate.
The additional profile record binds that confirmation to the existing geometry
hash; historical 48-well receipts remain unchanged, and no new run is claimed.

The full Cellvis slot-1 scanner-to-Squid chain is executable through
`HotelSquidAdapter`. `hotel_cellvis_handoff.py` binds the fresh, completed hotel
receipt to the accepted scanner geometry without rewriting historical evidence.
The scanner pickup uses the existing algorithm through the console's owned
service. Receipt age, hashes and single-use rules remain enforced.

Registration presents the original side at Z163.76, allows five ordinary
no-reads, then returns/releases in HOME and presents the opposite side at
181.77 degrees for at most five more triggers. A successful decode must be saved
in the registry; timeout, transport error, identity/profile mismatch or failed
registry write stops the chain. Two no-read sides return the plate to HOME and
block Squid. Contents are never inferred or copied from the earlier DNA plate.

After registration, the existing Squid executor runs its delivery portion only,
ending at the accepted empty-HOME checkpoint. It does not retrieve immediately
or start imaging. One human confirmation covers the full displayed route and
bounded scan procedure; cancellation and the 15-minute window apply inside phases.
The newly joined adapter is offline-tested; no live joined run is claimed.

## Execution and evidence

Existing compound executors retain their confirmation, custody, timing and
exact-job checks. The hotel HOME wrapper consumes a single pending human plan,
checks the registered profile/location and unchanged geometry, and writes intent
before dispatch. Fault, timeout or uncertain feedback retains `unresolved.json`
under `runs/composed_transfers`; no model tool can clear it or retry. Controller
receipts remain separate from operator observations. Registry reconciliation is
conservative: it does not label a controller result as visual confirmation.

Offline tests cover supported delegation, order/cycle preservation, required
registration, profile mismatch, no prefix execution, human-only single-use start,
uncertain completion and durable receipts. No live motion is part of these tests.
