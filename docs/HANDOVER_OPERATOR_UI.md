# Handover — S4 Operator Console (operator_ui/)

Audience: the next engineer/agent continuing this project. Companion doc:
`HANDOVER_MCP_SKILLS.md` (robot layer, math, calibration architecture —
read it first; this doc does not repeat the physics).

## 1. What it is / how to run

Human-in-the-loop Flask console: the operator watches the eye-in-hand
camera and presses buttons; the software executes single guarded steps
and reports. No agent decisions.

```
py operator_ui/app.py        ->  http://127.0.0.1:5002
```

- It is its OWN BRCAPI TCP client — mutually exclusive with the
  bioyond-s4 MCP server and Bioyond Works (one controller client).
- It holds the GigE camera (Release/Resume buttons; exclusive with MVS).
- The standalone `Misc/aruco/grab_aruco.py` reuses this package's
  service/sequence layers headlessly — changes here propagate there.

## 2. Architecture

```
app.py             Flask routes, Runner instance, TorqueRecorder thread,
                   points/roles/motion-order store (points.json)
robot_service.py   hardened robot layer: preflight guards, envelope box
                   (envelope.json), kinematic reach guard (base-centred),
                   ARRIVAL VERIFICATION (pose_after must match command,
                   1 mm / 0.5°), MID-COMMAND DROP RECOVERY (reconnect ->
                   settle -> judge by pose; NEVER resends), safe program
                   start (stop-first when paused; refuses while holding),
                   gripper jobs + torque report (SysVarI 10-16)
sequences.py       Runner (one background sequence thread, log, STOP
                   flag, published target) + all sequences + exact IK
                   (_ik_j2j3/_reach_block) + travel-leg order parser
camera_service.py  GigE frames (fresh-snap for vision, cached for view)
aruco.py / teach.py  thin wrappers over grab_skill solvers (live
                   constants, model stamps, anchors passthrough)
static/index.html  the whole frontend (vanilla JS, two tabs, pollers)
```

Concurrency: one motion lock in robot_service; one sequence at a time in
Runner; the torque recorder interleaves through the same motion lock.

## 3. Sequences (sequences.py)

- `seq_find_disk` — vendor teach convergence for the calibration disk
  (rotate to taught angle J4-aware, iterate to xy<0.3/rz<0.2/z<0.3,
  recovery ladders, publishes grasp + calibrated grip Z).
- `seq_find_aruco` — the ArUco pipeline: stamp-mismatch warning,
  center-view loop (tilt-aware view center), two agreeing solves,
  multi-viewpoint average (XY mean, **Z median**), ALL FOUR grab
  candidates (2 clamp axes × 2 wrist sides) with spans; feasibility =
  exact kinematics only (extension circle around base + predicted J2 +
  envelope). **The claw-window span gate was REMOVED by operator order
  ("I will take care of that") — span problems are logged/warned, never
  rejected.** Publishes the standard target (+ axis/span + anchor
  capture data).
- `seq_align` — J4-planned in-place rotation (≤30° chunks) + linear
  translate at hover Z.
- `seq_descend` — torque-guarded descent: telemetry check, 5-read
  baseline, 1.0/0.5 mm steps at speed 5, J1-vs-trend + J2-J4-vs-baseline
  (band floor from torque_config.json), first breach → stop, retreat
  1 mm, discriminate contact vs drift. Never grips.
- `seq_grip` — stepped torque-crossing close; reopens if the floor is
  reached empty.
- `seq_generate_anchor` — **vendor-exact** convergence (operator order):
  applies the FULL move_xyrz then FULL move_z every iteration (no capped
  steps); only hard REFUSALS (reach/J2/J4/envelope) remain, stopping
  cleanly instead of faulting; logs every capture filename + pose +
  errors; on convergence holds TWO anchor rows PENDING — the browser
  asks "was the run successful?" and only `/anchor_confirm` saves.
- `seq_calibrate_camera` — drives ~12 poses (rotations/hops/heights)
  over a FIXED marker, fits the full mount (incl. tilt/u_scale/mirror/
  h_scale), saves if RMS < 4, then AUTO-re-derives claw arm + wrist_rel
  from stored anchors (stamps match → grab-ready). **The target marker
  must be rigidly fixed — a marker on loose contents poisoned a fit
  live (see handover §11.9).**
- `seq_calibrate_aruco` — per-id disk calibration on a CONTRASTING
  background (edge-detect outline, marker→center offset in marker frame,
  rel_yaw, spans; annotated image shown for the operator's check).
- `seq_workflow` — pick→place→home over saved points (see §5).

## 4. UI tour (Console tab)

- Header: state chips, tab switch, E-stop reminder.
- Camera panel: live view, click-to-zoom crop, Snapshot/Release/Resume.
- Sequence log + detection panel (annotated detections).
- Connection/mode/enable/program card; jog pad (incl. fine Z 0.1-1 mm);
  envelope card (box + Disable toggle — state persists in
  envelope.json; the standalone grabber refuses when disarmed).
- Pipeline card: `1 Find disk`, `1b Find ArUco`, `1c Calibrate disk ID`,
  `1d Calibrate camera (auto)`, `0 Generate anchor (vendor)`;
  Z-calibration box (edits z_touch/margin → calibration.json);
  grasp-target box (fields editable; **"Save this target as point"**);
  `2 Align` (hover Z), `3 Descend`, `4 Grip` (open/floor), `5 Lift`,
  Release, STOP SEQ.
- Maintenance buttons: Save ArUco offset (jog-based), **Calibrate claw
  arm (2-press, bias-immune** — two wrist angles separate arm from
  camera bias), Clear ArUco offset, Save wrist relation.
- Torque feedback card: recorder + live chart; CLICK the chart to set
  the descent band (→ torque_config.json, used by seq_descend).

## 5. Points & Trajectory tab

- Isometric canvas auto-fitted to the envelope box: wireframe + 50 mm
  deck grid, saved points with drop-lines + role colors (start green /
  end orange / home blue), live yellow cross = current TCP, full
  trajectory preview once all roles are set.
- Click a point → Set as START/END/HOME / Delete. "Add CURRENT pose as
  point" (for home/park poses; grip points come from the grasp-target
  box which carries the calibrated grip Z).
- **Motion order between points**: presets (Z→Rz→XY default, Z→XY→Rz,
  Rz→Z→XY, Z→X→Y→Rz) or custom token list (z, rz, xy, x, y — omitted
  axes auto-complete). Persisted; the preview redraws to match; the
  workflow executes legs token by token.
- RUN workflow + travel Z + open E1. Choreography (operator-specified):
  claw travels CLOSED → start: descend to z+20 → OPEN → guarded descend
  → grip → slow lift → end: guarded descend (touchdown contact near the
  saved Z = success) → release → rise 20 mm → CLOSE → home. Contact
  ABOVE grip depth at START aborts before gripping; failed grip stops
  the run; STOP halts between steps.
- Store: `operator_ui/points.json` ({points, roles, motion_order}).

## 6. Config files (all operator-editable, all persisted)

| file | contents |
| --- | --- |
| `operator_ui/envelope.json` | soft box + enabled flag |
| `operator_ui/robot_params.json` | kinematic block (base/links/offsets), J2 min + margins, J4 limits, claw gap window, legacy radius guards |
| `operator_ui/torque_config.json` | operator-picked descent band |
| `operator_ui/points.json` | saved points, roles, motion order |
| `grab_skill/calibration.json` | all vision/claw constants + stamps (see the MCP handover §7) |
| `grab_skill/anchors.json` | ground-truth anchors |

## 7. Recipes

**Daily grab:** Connect → (auto/enable/start if needed) → place object →
1b Find ArUco → review target + way log → 2 Align → open claw → 3
Descend → 4 Grip → 5 Lift.

**New object id:** stick a marker (verify print scale if a new sheet) →
place on contrasting background → 1c → eyeball the rectangle → check the
clamp span vs 60-88 → if the marker is recessed, one guarded descent
measures grip_z_offset = contact TCP − marker Z (manual calibration.json
edit). The id belongs to the OBJECT — re-glue ⇒ recalibrate.

**Camera recalibration:** fix a marker RIGIDLY on the deck → 1d → it
auto-re-derives the claw arm from anchors and restamps ("grabs are
trustworthy again"). If no anchors: run 0 Generate anchor first (vendor
disk placed; confirm the dialog), or the 2-press jog flow + Save wrist
relation. Distrust any fit whose RMS is far above the 0.26 heritage.

**New arm port:** robot_params.json (limits; fit the kinematic block
from ≥4 WELL-SPREAD logged joint/pose pairs — narrow sectors produce
phantom fits) → 0 Generate anchor (vendor disk) → 1d (auto-derives arm)
→ z-touch via Z-cal box → 1c per object. Zero code edits.

**Fault recovery:** 3570/3571 (reach/joint limit) or 3608 (E-stop):
resolve the cause → Clear errors (operator-confirmed) → Enable → Start
program (safe-start) → verify pose → continue. Mid-command drops are
auto-recovered by the service (log says "recovered"); trust the pose.

## 8. Testing

`operator_ui/tests/test_offline.py` — 96 checks against the fake
controller (`bioyond-s4-mcp/tests/fake_controller.py`), no robot:
service guards + arrival verification, IK regression on live pose pairs,
both live fault targets, anchors (derive/gate/restamp), 4-way
candidates + span flags, per-id grip depth, find/align/descend/grip
sequences, a full simulated workflow with custom motion order, the
vendor-exact anchor loop refusal path, planner geometry, camera-fit
recovery on synthetic scenes (fixtures PIN canonical camera constants —
do not let live calibration leak into them). Run from `operator_ui/`.
Keep it green; add a regression for every new live lesson.

## 9. Known gaps / next steps

1. The pending deck grab (see MCP handover §13) — target solved and
   locked, execution paused by the operator.
2. Marker should move to the tray's rigid rim; then re-run 1c.
3. Workflow: per-leg motion orders (currently one global order); more
   than 3 roles (multi-stop routes) would be a natural extension.
4. `rz_alt` hint in seq_align is only meaningful for find_disk targets
   (ArUco candidates have per-way TCPs — re-run Find instead).
5. The span/claw-window check is warning-only by operator decision —
   revisit if unattended operation is ever wanted.
6. The MCP server lacks the drop-recovery the console has — port it.
7. UI has no explicit E-stop status chip (errors chip covers it).


## HOME / IDLE location contract (2026-11-10)

IDLE is the former true Home at X289.97/Y62.63/Z248.02/Rz-3.88. HOME now
means the calibration holder, with separate seating, clearance and grip poses.
Historical coordinates, controller route keys and trial hashes stay unchanged:
in the legacy procedures below, Home means IDLE unless explicitly marked HOME
holder. The old Home-area remains a distinct historical waypoint.

For a new experiment, use `operator_ui/plate_session.py` and
`Pick and Hold/plate_session_workflow.json`: full calibration once per valid
session -> grip -> lift 5 mm at speed 5 -> lower the same 5 mm at speed 5
into the unchanged HOME holder -> open E1 to 28 mm while seated -> raise the
EMPTY arm 30 mm at speed 137. Full calibration ends here, with no final IDLE
travel. Separately verify the full sweep -> orient -> verify three fresh E2
readings -> re-grip -> proof lift -> accepted destination route. The revised
calibration finish is implemented and offline-tested; its exact physical
trial is pending. Earlier 5 mm empty-clearance evidence is not that trial. Never rotate a held plate. The new near-holder
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

## Empty-arm recovery in Lacry (2026-11-11)

Researchers can use **Recover from fault**, or ask Lacry to recover the arm;
`plan_robot_recovery` proposes the checked operation and the existing Yes/No
confirmation starts it. Bioyond UI is not required for the supported recovery.

`operator_ui/empty_home_recovery.py` currently covers the first high wrist turn
of the recorded opposite-wrist Hamilton route. The operator must remove the
plate from the jaws, support it in HOME, clear the obstruction/path, release the
arm and supervise the E-stop. The planner checks the current pose/joints,
configuration and workspace. It clears faults once if necessary, enables the
controller, starts Lua with confirmed-empty jaws, returns in a monitored queue
at speed 5 to HOME clearance X312.5/Y-66.3/Z105.72/Rz89.84, and opens to28 mm.
The holder remains at its measured angle; this is not pickup or seating.

The live trial completed without reported faults and verified the final pose
and open jaws. Receipt:
`operator_ui/reports/plate_session/empty_home_recovery/5aa1280c44754017bf445f66576a9c66.json`.
The test did not establish loaded recovery or native `moveBackwards` behavior.
Other positions retain the existing nonmoving clear/enable option. A failure,
timeout, changed start, unsupported location or uncertain feedback stops the
attempt; the experiment and old failed receipts are not reset or retried.
After recovery, a new checked experiment plan is required.

## Lacry model — Sonnet 5.5 (2026-11-12)

`operator_ui/lacry_model.py` defaults to `claude-sonnet-5-5`. The optional
`LACRY_MODEL` environment variable overrides it at console startup. This replaces
the former `BIOYOND_AGENT_MODEL` setting and applies to Lacry and existing image,
pickup-analysis and developer-explanation calls. The saved Anthropic key is reused.
Lacry's `look_at_camera` tool returns image content directly to the same Sonnet
conversation; no separate camera agent is needed for researcher chat.

Sonnet requests omit sampling parameters, use adaptive thinking with medium
effort, and allow 8192 output tokens (including thinking). The request timeout is
60 seconds, with no automatic retry. Signed assistant blocks are retained unchanged;
live state and memory are appended to new turns instead of rewriting the system
prefix. Model history is not silently truncated. Incomplete, refused or oversized
responses stop before dispatching their tools. Existing host confirmation and
execution checks remain authoritative. Audit/UI output omits private thinking.

Read active settings with `GET /developer/api/lacry/model`. After changing the
setting, reload only an idle console. Refresh the browser to load updated labels.
An isolated live-model check is available from the repository root:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui/check_lacry_model.py --live
```

That check uses synthetic images and fake tools/telemetry. It blocks network
connections other than Anthropic HTTPS, checks image analysis, a follow-up turn
and tool planning, and writes `operator_ui/reports/model_checks/sonnet_*.json`.
It never authorizes or tests physical motion.
