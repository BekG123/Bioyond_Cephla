# Supervised Hamilton dilution authoring

Lacry turns a researcher's liquid-transfer request into a typed local draft,
native Hamilton simulation and conditional physical execution under one approval.
The conversational model fills a structured specification from the researcher's
answers. Deterministic code validates and compiles it; model-generated code and
arbitrary Hamilton HTTP paths are never executed.

## Researcher flow

1. Ask Lacry to draft independent dilutions. It reads Hamilton labware with
   `get_hamilton_authoring_catalog`, then asks for missing experimental details.
2. Provide stock and diluent identities/sites/wells, empty destination wells,
   dilution factors, final volumes, initial liquid volumes and minimum remainders,
   fresh tip addresses, and pipetting/mixing settings. `draft_protocol` saves only
   a local draft. No instrument write occurs.
3. `plan_hamilton_experiment(draft_id, plate_id)` displays exact wells/volumes,
   deck, inventory, mixing settings and requirements. The plate must already
   be at Hamilton site 4, with the empty arm at HOME clearance or IDLE.
4. One human Yes authorizes creation if needed, native simulation, and a live
   run if the simulation succeeds. The host verifies its fresh job ID,
   Simulation device identity, Completed outcome, every source/destination/
   volume and fresh tips. It then executes automatically, without a separate
   commissioning step, second Yes, or physical-validation trial.
5. Existing deck, calibration, arm-clearance and exact-job completion checks
   remain. Failed/stale simulation, changed inputs, Stop or timeout prevents
   further dispatch. `get_protocol_draft` exposes simulation and live results.

The older `plan_protocol_authoring(create|simulate|commission)` actions remain
available for standalone authoring or deliberately creating reusable recipes.
They are optional and are not the default experiment execution path.

Example starting prompt:

> Draft independent dilutions of the Tetrahymena cultures in A5–D5 of my Cellvis
> P24-1.5H-N plate, using Hamilton. Ask me for dilution factors, final volumes,
> medium location, empty destination wells, initial volumes, fresh tips and
> pipetting/mixing settings. Show the calculated transfers before creating or
> simulating anything on Hamilton.

## Initial scope

- Cellvis P24-1.5H-N transported plate at Hamilton site 4; exact native catalog
  geometry and 300 µL Framed Conductive Filtered tips (235903).
- Independent dilutions from existing stock, not serial/cascaded dilution.
  Diluent is transferred first, then stock; the destination is mixed afterward.
- 1–24 destinations, two fresh tips per destination. Each transfer must be within
  1–300 µL and representable in exact 0.1 µL increments. These are compiler bounds,
  **not wet-run qualification or accuracy claims**; native simulation and human
  review must also accept the method. No implicit rounding or multi-stroke split.
- Independent dilutions require empty destinations. The alternative `additions`
  specification supports occupied destination wells with explicit source,
  destination, added volume and mixing choice. Initial/final capacity and source
  minimum retained volume are checked; no liquid amount is guessed.
- The native aqueous liquid class, from-bottom heights, mix volume/cycles/speed
  and zero XY offsets are displayed. There is no automatic choice of biologically
  appropriate settings and no inheritance of old dry-mock plate offsets.
- One physical inventory cycle per combined experiment or commissioned recipe. Commissioning cannot
  overwrite a recipe or reset its consumed inventory. General authoring,
  automatic replenishment, arbitrary labware and serial dilution remain outside
  this version.

## Evidence and failure behavior

`operator_ui/reports/protocol_authoring/<draft-id>/draft.json` stores the typed
specification, live labware definitions, compiled requests, exact native protocol
and hash, simulation job/report, approval sources, and commissioning record.
Hamilton's existing owned-operation journal records every native request. Its
`active.json` blocks another operation after an uncertain write. No action is
resent on timeout; no automatic abort, reset, error clear or physical fallback is
performed by the authoring module. A persistent `executing_*` record after a host
crash is not eligible for redispatch.

Approved plans expire after ten minutes, bind the draft and settings hashes plus
Hamilton connection session, and are single use. Models cannot approve or call
the executor. Protocol creation, native simulation, commissioning and physical
execution are distinct decisions. Simulation is not evidence of live cell
viability, pipetting accuracy or a successful physical wet run.

## Validation and activation

Implementation: `operator_ui/dilution_protocol.py` and
`operator_ui/lacry_protocol_authoring.py`; existing Lacry chat/Yes-No controls and
`supervised_experiment.js` provide the UI. No accepted arm route was changed.

The compiler uses native shapes inspected from live protocols 12 and 13 and
catalog labware 128/8. Read-only captures and an older real simulation report are
in `operator_ui/tests/fixtures/dilution/`; all newly generated simulation results
in tests are fake and explicitly not physical acceptance receipts.

Run the offline tests with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and:

```powershell
py -B -m pytest operator_ui/tests/test_dilution_authoring.py -q -p no:cacheprovider
```

No new protocol was created or simulated on real Hamilton during implementation.
No recipe was commissioned. The first operator-approved creation/simulation,
human commissioning and supervised wet run remain to be performed using actual
experimental volumes and inventory.
