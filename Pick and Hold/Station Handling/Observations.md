# Squid — 20 October 2026

Operator accepted drop-off, empty return, pickup, and loaded return.

- Taught seated pose: X226.30, Y373.59, Z266.19, Rz89.11.
- Leave plate: Home → Squid at 137, open E1=5 at speed 5, lift empty jaws 5 mm at speed 5, return Home at 137.
- Retrieve: Home → Squid with E1=5, close to 3.7 at speed 5, lift 5 mm at speed 5, return Home at 137.
- Squid stays in its taught loading position. Microscopy completion is currently an explicit operator signal; actual imaging is not connected.
- Both researcher buttons and Lacry station-handling requests use `operator_ui/squid_handling.py`. One confirmation starts the complete routine; Stop/failure prevents the next step. No automatic controller preparation or fault clearing.
- Each plan, step result, jaw report, and travel sample is recorded by the existing JSONL audit. Accepted trial JSONs are in `operator_ui/demonstrations/reference_grip/`.
- Hamilton local handling is still unvalidated; these settings commission Squid only.

The Home planner now recognizes the accepted 0–5 mm lifted Squid position and keeps the original four reverse targets. Limits and joint-winding checks are unchanged.

# Hamilton — 20 October 2026, integration only

- Added researcher buttons and Lacry actions `hamilton_dropoff` / `hamilton_retrieve`, also available through `plan_station_handling`. Both start and finish at true Home.
- Same settings as Squid: opening5, closing3.7, jaw speed5, lift5mm at speed5, travel137. Hamilton seated Z38.61; lifted Z43.61. Original XY/wrist and three-target Home route retained; no Home-area detour.
- Shared jaw/settling/lift executor remains in `operator_ui/squid_handling.py`; exact Hamilton geometry and empty-travel evidence checks live in `operator_ui/hamilton_handling.py`.
- Hamilton is an executable supervised trial, not accepted loaded handling. Pause for inspection before jaw movement and after the lift. Rejection, Stop, fault or uncertain grip prevents the next step. No automatic program restart, camera calibration or instrument-completion inference.
- The local workspace exception is limited to the exact five-millimeter lift at the Hamilton endpoint. The return recognizes that lifted column; normal workspace, joint, winding, evidence and telemetry checks remain.
- 83 focused checks pass, including real Lua with fake hardware, both stations, failed grip/rejected inspection, altered geometry/evidence, and experiment-preview restrictions. Researcher browser checks pass with zero hardware calls. No physical handling trial during integration.

## Hamilton inspection UI correction — 20 October 2026

The first live routine reached Hamilton Z38.61/E1≈3.70, then waited before jaw movement. Status returned503 because it deep-copied a thread Event; the approval button also used a timestamp instead of the review ID. Codex stopped the waiting workflow, preserving jaw position. No release/lift occurred. Corrected both issues and added real-thread state/approval and browser-token regressions; physical handling remains unvalidated. Details: `operator_ui/reports/hamilton/inspection_ui_failure_20261020.json`.

## Complete Hamilton-to-Squid requests — 20 October 2026

- Chat selected only `hamilton_retrieve` for “go back to Hamilton, take the plate, and bring it to Squid.” That routine correctly ended at Home, but omitted the requested destination.
- Added `retrieve_hamilton_to_squid` (pickup → Home → Squid, keep held) and `deliver_hamilton_to_squid` (also release at Squid and return Home empty). Existing routes, jaw settings, inspection stops and feedback checks are reused in one confirmed plan.
- A later, separately requested Squid drop-off stopped on changed gripper feedback. Chat then described a nonexistent pending plan. Each model turn now receives fresh host state and asynchronous outcomes; stale “reply Yes” claims are corrected by the host.
- Offline tests cover the complete sequence with real Lua/fake hardware, partial failures, changed jaws, altered plans and stale chat state. No physical trial or changes to speed, routes or gripper thresholds in this fix.

## Squid completion connection — 20 October 2026

- Researcher **Connect to Squid** now follows the running local Squid app through its native TCP status server (127.0.0.1:5050) and native acquisition `run.json`. In Squid, enable **Settings → Enable MCP Control Server**, or launch with `--start-server`. Python Exec is unnecessary.
- Tracks the exact run ID, process session, experiment, progress, terminal reason and image count. Completion requires the acquisition thread to be idle and a successful native outcome. Old jobs, aborted/error runs and connection gaps do not become fresh successful completions.
- Lacry receives chat notifications and can query `get_squid_status`. Events are saved to `operator_ui/logs/squid/events.jsonl` and its memory. Monitoring never starts imaging or robot retrieval; holder clearance and movement confirmation remain separate.
- The active checkout was `C:\Users\Cephla\AppData\Local\Temp\claude\squid-latest\software`, launched with `--simulation`, rather than the older desktop copy. Restarted only that simulator with its status server enabled.
- End-to-end native mock acquisition passed: run `00c5f47e334f46cd94ac29486be9ea61`, one saved TIFF, 0.58 seconds, zero reported imaging errors. Lacry explicitly reported mock completion; no robot commands. Evidence: `operator_ui/reports/squid_connection/Lacry_mock_20261020T062329_9bc9c1/trial.json`.
- Real hardware imaging remains untested. Hamilton instrument automation remains a template.

## Home startup refusal recovery - 20 October 2026

- An old held-plate startup refusal created two failed records and blocked every later Home request. Travel had never started.
- Home now records explicit pre-start refusals separately from interrupted/uncertain travel. Only proven refusals allow a fresh checked plan; faults, limits, route confirmation and uncertain-motion review remain.
- Lacry receives the current history assessment and reports the host's actual refusal instead of inventing reset advice.
- Reviewed both exact Oct 20 records, preserving original files, failure statuses and logs under `operator_ui/reports/home_attempt_reviews/startup_refusal_1792501655449706400/`.
- Home, startup, workflow, route-history, chat and browser regressions pass. Loaded the update and successfully previewed a fresh IK Home plan from the live pose, then cancelled the preview. No arm movement or controller reset.

### Follow-up: rejected Home confirmation

- A subsequent Yes failed before the runner started: overlapping hand-guiding status reads could report a mode change. This preflight rejection incorrectly created another uncertain-motion record.
- Status reads now wait briefly for the shared lock and fetch fresh feedback. Home records the dispatch boundary; failures before it are auditable preflight refusals, while failures at/after dispatch remain uncertain. Rejected confirmations discard their old Yes.
- Preserved and reviewed the exact record in `reports/home_attempt_reviews/preflight_refusal_1792503633276607400/`. All 142 Home, hand-guiding and Lacry regression checks passed, including the confirmation path with fake hardware. Reloaded and verified a live Home preview; no physical motion test.

## Experiment status and measured Hamilton return - 20 October 2026

- Added experiment bars beneath the connection header: current step, completed-step count, confirmation/inspection waits, stopped/completed outcomes, and a separate Squid imaging row. Unknown progress stays indeterminate; mock/historical imaging is labelled. Desktop/mobile browser checks pass, including refresh and connection loss.
- Current Hamilton pose was X195.051/Y-360.241/Z49.087/Rz-2.149, near the older taught endpoint rather than the newer Z38.61 station. It fell through to the ordinary workspace box.
- Added a hash-pinned measured return reference with 0.05 pose tolerance and existing joint-configuration checks. It uses the existing exit at X195.88/Y-357.36/Z212, boundary X215.74/Y-249/Z212, then true Home at speed 137. General workspace limits and the commanded Hamilton destination are unchanged.
- IK and real-queue/fake-controller tests pass. Loaded both updates and verified a fresh live Home preview, then cancelled it without motion. The small adapted initial segment still requires the normal physical-clearance confirmation before execution.

## Slower final Squid descent - 20 October 2026

- Researcher reported edge contact during Squid entry. Reduced only the final 20.05 mm descent from 137 to 40 mm/s; transit and return remain 137. Taught coordinates and grip/pickup settings are unchanged.
- Existing Lua queue executes the three transit targets, confirms arrival, then starts the final target at 40. Stop, failed completion or changed grip blocks descent. No republish needed.
- Applies to Lacry direct travel, drop-off/retrieval, Hamilton-to-Squid and repeated workflows. Speed policy is included in plan evidence; old confirmations cannot silently use a changed policy.
- 116 focused checks passed with fake hardware, including real Lua speed serialization. Candidate: `operator_ui/reports/squid/slower_descent_40_20261020/candidate.json`. No physical trial or contact-clearance validation yet; original trials retained.

## Home followed by full calibration - 20 October 2026

- Chat promised Home then calibration, but the model queued only Home. The completed Home log correctly contained no calibration action.
- Added one confirmed workflow for `move_home, full_calibration`, using the existing Home route/IK and pickup entry points. One reservation covers both; Home completion, saved position and its attempt record are checked before calibration. Fault, Stop, changed settings or uncertain completion stops the chain. Already at Home means a position check without redundant travel.
- Plan announcements now use the compiled steps, not model promises or model-supplied summaries. Progress includes the initial Home plus the existing six pickup stages.
- 76 focused checks and the fixture-only browser checks passed, including real IK/Lua wrappers with fake hardware. A broader historical Home suite exposed five unrelated `test_loaded_home_trial` failures: its pinned baseline differs from current kinematics/workspace; that historical replay was not changed. No physical trial of the combined workflow.
- Loaded the update while idle. Live Lacry correctly proposed all seven stages with one confirmation; cancelled this diagnostic preview without execution. Robot remained at saved Home X289.97/Y62.63/Z248.02/Rz-3.88 with no reported faults.

## Squid descent reduced again - 20 October 2026

- Operator reported harsh landing. The last log confirms descent at 40 mm/s, followed by a stop for changed gripper feedback; this was not recorded as an accepted trial.
- Reduced only the final 20.05 mm descent to 10 mm/s. Transit/return remain 137; geometry, jaws and slow pickup lift are unchanged. Researcher display and Lacry instructions match the new policy.
- 87 focused checks passed, including real Lua with fake hardware, direct/compound travel, drop-off/retrieval and rejection of the previous 40 mm/s descent. Loaded while idle; controller program remains stopped. No physical retry, fault reset or program start.
- Preserved prior candidate and live failure snapshot under `operator_ui/reports/squid/slower_descent_10_20261020/`. New landing speed awaits physical acceptance; slowing does not resolve unknown edge contact or changed grip.

## Calibration followed by Squid - 20 October 2026

- The requested Home/calibration/Squid combination fell through the planner's full-calibration rejection. Lacry misinterpreted “researcher pickup workflow” as requiring hand-guided teaching. Full calibration already uses the automatic camera/saved pickup routine.
- Added the optional taught Home-to-Squid continuation under the same workflow reservation and confirmation. It starts only after completed pickup/Home, with live pose, joints, grip, Auto readiness and unchanged route evidence checked. It never restarts a loaded controller. Travel retains the plate; release/imaging remain separate actions.
- Planner refusals now reach chat verbatim and cancel stale proposals; a refusal cannot turn into an invented teaching requirement or a different plan that skips pickup.
- 71 focused checks passed, including actual planner/Lua execution against fake hardware. Loaded while idle/stopped/disabled. Live Lacry proposed all eight stages from the current Manual state; the diagnostic preview was cancelled without movement. Physical execution of this complete chain remains untested.

## Drop-off when already seated at Squid - 20 October 2026

- Travel succeeded at final descent10, but subsequent drop-off requests were rejected because the handling planner only accepted Home as its starting station. No release command was issued.
- Squid drop-off/retrieval now also accept the exact taught seated pose with the expected joint configuration and jaw position. From there they skip outbound travel, use the existing jaw setting (release5/pickup3.7), lift5mm at speed5, and return Home137. Raised/offset poses, changed feedback, faults and Stop remain blockers; release confirmation explicitly requires full plate support.
- Lacry now knows this starting option. Broadened refusal grounding and stale-plan detection to prevent invented pending plans and teaching requirements after a station-tool rejection.
- 94 focused checks passed, including real Lua against fake hardware. Loaded and verified a live three-step drop-off preview at the seated Squid pose; cancelled it without arm/jaw movement. The existing accepted submotions are reused; this new starting entry point has not been physically executed by the assistant.

## Automatic Squid experiment - 20 October 2026

- Added one confirmed sequence: full calibration/pickup → Squid drop-off → Home wait → exact imaging job completion → retrieval to Home. It reuses the existing robot routes, jaw settings and slow Squid landing; no repeated routine Yes prompts.
- The optional `operator_ui/squid_bridge/launch.py` add-on captures the selected Squid GUI settings on its Qt thread and checks them again before starting. Shipped Squid files remain unchanged; Python Exec stays disabled. Unsupported focus maps/offsets are reported rather than omitted.
- Settings, imaging IDs, results and failures go to `reports/autonomous_squid/<run>/workflow.json` with a settings YAML. Failed/uncertain jobs stop progression; Stop targets only the owned acquisition. The arm stays reserved during imaging and retrieval waits for the microscope's loading-position feedback.
- Offline planner/Lua, Qt add-on and browser tests passed. No real arm motion or native imaging run was started for this change. The operator is away: Squid and Flask were not restarted; loading and the complete physical trial remain pending.
