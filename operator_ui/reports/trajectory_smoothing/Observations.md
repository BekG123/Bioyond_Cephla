# Grouped Hamilton replay — October 16, 2026

- Returned from the previous stopped pose along the taught route, with IK/joint checks: **114.8 s**, successful. Original replay start: X276.03, Y79.94, Z166.41, Rz1.98. Saved Home remains unchanged.
- Full grouped replay to Hamilton at **speed 40**: **150.3 s total**, including 15.7 s preparation/upload and 134.5 s movement. Completed at X195.338, Y−360.310, Z48.609, Rz−1.901 in controller feedback.
- **543 → 132 commands**; planned path change at most **0.248 mm / 0.096°**. Joint/reach and measured-path checks remained active. No controller errors; all **748 samples valid**.
- Over the same first ~64.5% of the route: movement **185.2 → 88.1 s**; sampled near-stationary time **12.09 → 0.49 s**. Earlier run stopped there, so full-route times cannot be compared directly. Matched comparison point differs by 0.171 mm.
- Fewer pauses are supported by ~5 Hz telemetry; equivalent smoothness to vendor Home is **not yet measured**. Corner blending remains unchanged (`zone=-1`).
- Recordings: [return](../../demonstrations/return_path_trials_20261016_131713/trial_30740_31309.json), [full Hamilton replay](../../demonstrations/return_path_trials_20261016_131713/trial_31464_32211.json), [comparison](hardware_comparison.json). Continuous logging remains active.

## Offline middle-loop removal

- Found two middle loops; replacing them with 4.61 mm and 4.70 mm connectors saves **750.0 mm (41.3%)** of travel. Initial and final approach geometry is preserved.
- Shortened route groups to **78 commands** using the original 0.25 mm / 0.1° tolerances. Forward/reverse IK and five offline tests pass.
- **Not executed.** Two new connectors need clearance review; the first reaches 2.19 mm outside the old reference path in the sampled check. Production replay remains unchanged. [Candidate and plots](pruned_middle/Review.md).

## Approved 78-point hardware return — 15:25–15:27 PDT

- After operator approval, executed the exact shortened route in reverse: **Hamilton → recorded Home-area**, speed **40**, **78 commands**, **99.57 s total** including preparation/upload.
- Completed at **X276.03, Y79.94, Z166.41, Rz1.98°**. No controller errors; **496/496 samples valid**. Maximum sampled deviation from the approved route: **0.116 mm / 0.018°** (controller feedback, not external metrology).
- Original recording and saved Home unchanged. The separate hash-bound, one-run permission was consumed. Monitoring remained **2 mm / 2°**, relative to the approved shortened route. Continuous logging remains active.
- [Full hardware recording](../../demonstrations/return_path_trials_20261016_131713/trial_38117_38612.json). The earlier offline-only note records the state before this approval and test.

## Z-motion refinement — prepared after the 78-point run

- Measured Z-speed dips from ~21 to **4.5–4.7 mm/s** coincide with the artificial Z155.71 and Z204.07 command boundaries. The 142.83 mm straight lift was split by the 50 mm grouping cap.
- Implemented bounded vertical-run coalescing: **78 → 75 commands**. The long lift becomes one command; a 55.06 mm lift becomes one instead of two. Maximum route change **0.038 mm / 0.017°**, with endpoint detail and real bends preserved.
- **60 offline tests pass**, including the actual 75-command route in both directions through Lua with fake hardware. No new hardware replay yet. Controller blending, speed, acceleration and jerk settings are unchanged. [Diagnosis and plot](vertical_smoothing/Review.md).

## Straight-transfer candidate — intermediate bends removed

- Proposed **three segments**: vertical lift to Z253.80, straight XY/yaw transfer, vertical descent to the station endpoint. Travel **740.16 mm**, another **30.6% shorter** than the loop-pruned route.
- Both directions pass full-segment IK; two focused tests pass. No intermediate horizontal turns or Z waypoints; the two vertical/horizontal transitions remain.
- **Offline only; not loaded or executed.** New transit and full vertical columns need clearance review, particularly above Hamilton from Z111 to Z253.8. Existing segment caps and replay permissions are unchanged. [Coordinates and preview](straight_transfer/Review.md).

## Straight-transfer hardware trials — 15:48–15:58 PDT

- The subsequently approved **Z253.8** trial stopped after **31.15 s** with an **axis-3 collision report**, near X226.54, Y−200.48. The monitor stopped the controller. The cause is not established by telemetry. [Failed run](../../demonstrations/return_path_trials_20261016_131713/trial_44868_45021.json).
- After the operator lowered the arm, cleared errors and confirmed both revised routes clear, returned at **speed 40**: level at Z212.21 to X276.03, Y79.94, then down to Z166.41. **28.55 s**, two commands, no controller errors, **143/143 valid samples**. [Return recording](../../demonstrations/return_path_trials_20261016_131713/trial_47576_47718.json).
- Revised **Home-area → Hamilton**, **speed 40**, **Z212**, three commands: lift, straight transfer, descend. **34.09 s total**, **169/169 valid samples**, no controller errors. Completed at **X195.340, Y−360.310, Z48.608, Rz−1.900°** in controller feedback. [Recording](../../demonstrations/return_path_trials_20261016_131713/trial_47808_47976.json), [route](straight_transfer_212/candidate.json).
- Timing reference: earlier **132-point forward run: 150.33 s**; **78-point reverse run: 99.57 s**. These are total task durations, with different preparation times; the 78-point run also travels in the opposite direction. The new geometry is shorter (656.56 mm), so this is not a smoothing-only comparison. Three segments remove intermediate stops, but do not establish jerk-free motion or vendor-Home-equivalent smoothness.
- **53 offline checks passed** before execution. Each separate one-run permission is consumed; joint/reach and measured-route checks remained active. Earlier recordings and saved Home remain unchanged. Continuous recording stays active.

## Forward entrance refinement — 16:05–16:06 PDT

- Operator reported a slight backward entrance motion and requested **3 mm forward toward Hamilton**. Kept the endpoint unchanged; moved the hover 3 mm short along the approach to **X195.88, Y−357.36, Z212**, then advanced during descent. This changes entrance geometry, not controller acceleration or blending.
- Returned along the previous Z212 route at speed 40: **44.63 s** including preparation, no errors. [Return recording](../../demonstrations/return_path_trials_20261016_131713/trial_49902_50123.json).
- Revised forward replay at speed 40: **33.94 s**, versus **34.09 s** for the previous forward Z212 run; effectively similar duration. **169/169 valid samples**, no controller errors, same Hamilton endpoint. [Recording](../../demonstrations/return_path_trials_20261016_131713/trial_50239_50407.json), [candidate](entry_forward_3mm/candidate.json).
- From the sampled point nearest the hover, measured forward advance was **3.037 mm**, with no backward sample steps; maximum sampled route deviation **0.0051 mm**. These are controller feedback measurements (~5 Hz), not external metrology or proof about all arm-link motion. Visual acceptance is pending.
- **55 offline tests passed**. Saved reusable workflow as `skills/trajectory-deblur`, also installed in the user's Codex skills directory. Preserve this candidate and the prior baseline until operator preference is known.

## Speed 47 in both directions — prepared, awaiting publication

- Requested speed 47 for research. Installed Lua 220101 caps queue speed at 40; prepared **220102**, capped at 47, in `main_hostpoint_trajectory_47.bin`. Host allows 47 only for these separately approved trials; ordinary replay remains capped at 40.
- Exact refined geometry is unchanged. Planned order from current Hamilton: **Hamilton → Home-area**, then **Home-area → Hamilton**, each three commands with its own consumed-on-attempt permission. Reverse route is checked through full-segment IK.
- Offline checks cover both directions at 47 through actual Lua with fake hardware, refusal above 47, refusal of 47 on old Lua without commands or permission consumption, and continued speed-40 compatibility.
- **No speed-47 hardware movement yet.** Desktop publishing unavailable: Computer Use reports its native pipe is missing. Package must be published in Bioyond Works, then verified on the controller. Prior results and permissions remain intact.

## Speed-47 hardware results — 16:22–16:23 PDT

- Operator published the package; fresh program start verified **Lua 220102 / maximum 47 mm/s**. Startup torque-report request timed out; fresh state/pose were checked before any path dispatch. No blind resend. This diagnostic issue remains unresolved.
- **Hamilton → Home-area: 29.34 s**, three queued commands, **146/146 valid samples**, no controller errors. Endpoint X276.03, Y79.94, Z166.408, Rz1.98. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_54961_55106.json).
- **Home-area → Hamilton: 29.32 s**, three queued commands, **146/146 valid samples**, no controller errors. Endpoint X195.337, Y−360.309, Z48.609, Rz−1.901. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_55210_55355.json).
- Same forward geometry at speed 40 took **33.94 s**: speed 47 reduced measured task duration by **4.61 s (13.6%)**. Both forward sequences logged queue dispatch at 0.2 s. One trial per speed is not a repeatability or statistical result; smoothness preference remains for the operator to assess.
- Sampled forward entrance advance was **3.064 mm** from the sample nearest the hover, with at most **0.00044 mm** backward sample change; maximum sampled path deviation **0.0041 mm**. Values are controller feedback (~5 Hz), not external metrology. Commanded entry remains exactly the rounded 3 mm candidate.
- Both one-run permissions consumed. Continuous logging remains active; original recording, speed-40 trials and saved Home are retained. Current arm endpoint is Hamilton.

## Speed 55 — prepared, not executed

- Operator requested the next speed trial at **55**. Prepared exact forward/reverse copies of the successful 3 mm entrance path, with separate one-run grants and the corresponding speed-47 trials as baselines. No geometry change.
- Package `main_hostpoint_trajectory_55.bin` uses **Lua 220103** with a 55 ceiling. Only the trajectory Lua module differs from the speed-47 package. Host permits 55 only for these research profiles; general Cartesian cap remains 50 and ordinary replay 40. Controller collision settings remain unchanged.
- **64 offline tests pass**, including both directions through actual Lua with fake hardware, rejection of 55 on versions 220101/220102 before commands or grant consumption, rejection above 55, and compatibility with existing speed-40/47 replay.
- **No speed-55 hardware run yet.** Requires publishing 220103 and fresh version verification. Both successful speed-47 runs and the prior binaries remain preserved.

## Speed-55 hardware results — 16:31–16:33 PDT

- Operator published; fresh program start verified **Lua 220103 / maximum 55 mm/s**. Startup torque-report timeout recurred; fresh pose/status were checked before dispatch. This reporting issue remains unresolved.
- **Hamilton → Home-area: 25.74 s**, **129/129 valid samples**, no controller errors. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_57862_57990.json). Versus speed 47's 29.34 s: **12.3% less time**.
- **Home-area → Hamilton: 25.57 s**, **128/128 valid samples**, no controller errors. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_58084_58211.json). Versus speed 47's 29.32 s: **12.8% less time**; versus speed 40's 33.94 s: **24.6% less time**. Same candidate geometry and three queued commands; dispatch logged at 0.2 s in both speed-55 trials.
- Forward entrance advanced **2.999 mm** from the sample nearest the hover, with no backward sample steps. Maximum sampled route deviation **0.0041 mm**. Final logged Hamilton pose **X195.337, Y−360.309, Z48.608, Rz−1.901**. These are controller feedback values, not external accuracy measurements; single trials do not establish repeatability or smoothness preference.
- Both one-run permissions consumed. Continuous logging remains active. Earlier trials, saved Home and prior binaries remain intact; arm finished at Hamilton.

## Speed 70 — prepared, not executed

- Requested next trial at **70**, using identical Z212 / 3 mm entrance geometry in both directions. Baselines are the corresponding successful speed-55 recordings (25.74 s reverse, 25.57 s forward).
- Prepared `main_hostpoint_trajectory_70.bin`, **Lua 220104**, capped at 70. Only the trajectory module differs from the speed-55 package. Host permits 70 only for these two reviewed research variants; controller collision, acceleration and blending settings are unchanged.
- **68 offline tests pass**, including exact forward/reverse transmission through actual Lua with fake hardware, refusal above 70, refusal on older modules before commands or permission consumption, and compatibility with earlier speeds.
- **No speed-70 hardware run yet.** Publishing and fresh version verification are required. The earlier successful trials, binaries and saved Home remain preserved.

## Speed-70 hardware results — 16:39 PDT

- Operator published; fresh program start verified **Lua 220104 / maximum 70 mm/s**. Known startup torque-report timeout recurred; fresh pose/status checked before dispatch. Logging active and valid; reporting timeout remains unresolved.
- **Hamilton → Home-area: 20.51 s**, **102/102 valid samples**, no controller errors. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_59988_60089.json). Speed-55 baseline 25.74 s: **20.3% less time**.
- **Home-area → Hamilton: 20.66 s**, **103/103 valid samples**, no controller errors. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_60158_60260.json). Speed-55 baseline 25.57 s: **19.2% less time**. Exact same three-command path; no acceleration or blending change.
- Sampled forward entrance advance **3.000 mm**, maximum backward sample change **0.00036 mm**, maximum sampled route deviation **0.0045 mm**. Final logged pose **X195.342, Y−360.310, Z48.608, Rz−1.899**. Controller feedback is not external metrology; one run per direction does not establish repeatability, payload performance or operator smoothness preference.
- Both one-run permissions consumed. Continuous recording remains active, prior trials preserved, arm finished at Hamilton. These are successful trials, not an automatic change to the default operating speed.

## Speed 80 — prepared, not executed

- Requested next trial at **80**; exact Z212 / 3 mm entrance path retained in both directions. Baselines are the corresponding speed-70 recordings (20.51 s reverse, 20.66 s forward).
- Prepared `main_hostpoint_trajectory_80.bin`, **Lua 220105**, capped at 80. Only the trajectory module differs from the speed-70 package. Host allows 80 only for these two research variants; controller collision, acceleration and blending settings are unchanged.
- **72 offline tests pass**: both directions through actual Lua with fake hardware, refusal above 80, old-version refusal before commands or grant consumption, prior-speed compatibility, and package integrity.
- **No speed-80 hardware run yet.** Publishing and fresh version verification required. Prior recordings, binaries and saved Home remain preserved.

## Speed-80 hardware results — 16:44–16:45 PDT

- Operator published; fresh program start verified **Lua 220105 / maximum 80 mm/s**. Startup torque-report timeout recurred; fresh pose/status checked before dispatch. Reporting issue remains unresolved.
- **Hamilton → Home-area: 18.37 s**, **92/92 valid samples**, no controller errors. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_61675_61766.json). Versus speed 70's 20.51 s: **10.4% less time**.
- **Home-area → Hamilton: 18.45 s**, **92/92 valid samples**, no controller errors. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_61841_61932.json). Versus speed 70's 20.66 s: **10.7% less time**. Same exact three-command geometry; no acceleration or blending change.
- Sampled entrance advance **2.996 mm**; maximum backward sample change **0.00027 mm**; maximum sampled path deviation **0.0046 mm**. Final logged pose **X195.339, Y−360.310, Z48.609, Rz−1.900**. Controller feedback is not external metrology; single runs do not establish repeatability, payload performance or subjective smoothness.
- Both permissions consumed; continuous recording remains active. Prior trials and saved Home retained; arm finished at Hamilton. Default operating speed is unchanged.

## Final speed-100 experiment — prepared, not executed

- Operator requested **100 as the final experiment** to study speed versus time. Exact Z212 / 3 mm entrance geometry retained in both directions; speed-80 trials (18.37 s reverse, 18.45 s forward) are immediate baselines.
- Prepared `main_hostpoint_trajectory_100.bin`, **Lua 220106**, capped at 100; only trajectory module differs from the speed-80 package. Host permits 100 only for these two reviewed variants; hardware collision, acceleration and blending settings are unchanged.
- **76 offline tests pass**, including both directions through actual Lua with fake hardware, rejection above 100, refusal on older modules before commands or permission consumption, prior-speed compatibility and package integrity.
- **No speed-100 hardware run yet.** Requires publishing and fresh version verification. After execution, compare all same-geometry speeds (40, 47, 55, 70, 80, 100) by direction; do not mix earlier geometries or long startup preparation into the speed effect. Single trials describe this session, not repeatability. Prior recordings and binaries preserved.

## Speed-100 hardware results — 16:50 PDT

- Published Lua **220106 / maximum 100** verified. Startup torque-report timeout recurred; fresh state checked before dispatch. This reporting issue remains unresolved.
- **Hamilton → Home-area: 15.31 s**, 77/77 valid samples. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_63245_63321.json).
- **Home-area → Hamilton: 15.33 s**, 77/77 valid samples. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_63408_63484.json). Both completed without controller errors; arm finished at Hamilton. Default operating speed unchanged; continuous recording remains active.
- Forward sampled entrance advance 2.999 mm, no backward sampled step, maximum sampled route deviation 0.0063 mm. Controller feedback is not independent physical metrology.
- [Speed/time chart](speed_comparison/speed_vs_time.png) and [source comparison](speed_comparison/comparison.json): identical path at 40/47/55/70/80/100; no comparable reverse run at 40. Forward time fell from 33.94 to 15.33 s; 80→100 saved 3.12 s (16.9%). Single trials show real time savings but do not establish an optimal operating speed, repeatability or payload performance. Speed 47 has no demonstrated mathematical optimum; selecting a production speed also needs smoothness and task-success evidence.

## Speed 130 — prepared, awaiting publication

- User requested a further speed-130 experiment. Prepared identical geometry in both directions, with separate one-run permissions and speed-100 recordings as baselines (15.31 s reverse / 15.33 s forward).
- Built `main_hostpoint_trajectory_130.bin`, Lua **220107**, SHA256 `86c3a86dc74eaf890fc22f108d0407e49f2962d044f0ff422cd537f05e6c3e66`. Only the trajectory module differs from the retained speed-100 package. General replay limits, controller collision settings, acceleration and blending are unchanged.
- **80 offline tests pass**, including exact forward/reverse commands through real Lua with fake hardware, rejection above 130, rejection by all earlier modules without consuming permission, prior-speed compatibility, Stop/cancel behavior and package integrity.
- Local vendor hardware manual p15 specifies maximum TCP speed 1400 mm/s; that specification does not validate this specific trajectory at 130. The installed queue still requires the new package to be published and freshly verified before movement.
- Backend reloaded with program stopped and hand-guiding off; reconnected at Hamilton with no reported errors. **No speed-130 motion yet.** Trial recording remains enabled. Publication is the outstanding deployment step.

## Speed-130 hardware results — 16:58–16:59 PDT

- Published Lua **220107 / maximum 130** freshly verified. Switching to Auto disabled the servo; the rejected start was resolved by checking state and explicitly enabling before starting. Known startup torque-report timeout recurred; fresh pose/status checked before dispatch. Startup reporting issue remains unresolved.
- **Hamilton → Home-area: 12.61 s**, 64/64 valid samples, no controller errors. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_65856_65919.json). Versus 100: 2.71 s / 17.7% less time.
- **Home-area → Hamilton: 12.26 s**, 62/62 valid samples, no controller errors. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_66010_66071.json). Versus 100: 3.06 s / 20.0% less time. Same geometry, acceleration and blending settings.
- Sampled forward entrance advance 2.994 mm; no backward sampled step; maximum sampled path deviation 0.0121 mm. These are controller-feedback measurements, not external metrology or a repeatability study. Operator smoothness acceptance remains unknown.
- Both permissions consumed; recordings preserved and [comparison chart](speed_comparison/speed_vs_time.png) updated. Arm finished at Hamilton; continuous recording active; default operating speed unchanged.

## Final speed-137 experiment — prepared, awaiting publication

- User requested 137 with a 10-second objective. Exact same forward/reverse path prepared; speed-130 baselines are 12.61 s reverse and 12.26 s forward. A 5.4% increase alone suggests roughly 11.6–12 s, not a guaranteed 10 s.
- Built `main_hostpoint_trajectory_137.bin`, Lua **220108**, SHA256 `9779e7ebda5a403aef94a3bf7dfcbaa2abfc6c81d4e002c6be2d234f90d18d7f`. Only trajectory module differs from speed 130; general motion limits, acceleration, blending and collision settings unchanged.
- **84 offline tests pass**, including both directions through real Lua with fake hardware, rejection above 137, all earlier-controller refusals before commands/permission consumption, previous-speed compatibility, Stop/cancel and package integrity.
- Backend reloaded with program stopped and hand-guiding off; reconnected at Hamilton without controller errors. **No speed-137 movement yet.** New package must be published and freshly verified; separate one-run permissions remain unused. Prior trials preserved.

## Speed-137 hardware results — 17:02–17:03 PDT

- Published Lua **220108 / maximum 137** freshly verified. Startup torque-report timeout recurred; fresh pose/status checked before dispatch. Reporting issue remains unresolved.
- **Hamilton → Home-area: 11.69 s**, 59/59 valid samples, no controller errors. [Reverse recording](../../demonstrations/return_path_trials_20261016_131713/trial_67055_67113.json). Versus 130: 0.92 s / 7.3% less time.
- **Home-area → Hamilton: 11.74 s**, 59/59 valid samples, no controller errors. [Forward recording](../../demonstrations/return_path_trials_20261016_131713/trial_67224_67282.json). Versus 130: 0.52 s / 4.3% less time. **10-second objective not achieved.** Same three-command geometry and motion settings apart from speed.
- Sampled forward entry interval advanced 3.065 mm (nearest hover sample includes a little preceding transfer), no backward sampled step, maximum sampled route deviation 0.0094 mm. Controller feedback is not external metrology; one run per direction cannot establish repeatability or subjective smoothness.
- Both one-run permissions consumed; recordings and [comparison chart](speed_comparison/speed_vs_time.png) saved. Arm finished at Hamilton; continuous recording stays active; default speed unchanged. No further experiment started.

## UI route and developer pickup learning

- Added the exact latest tested Home-area ↔ Hamilton route to Researcher and Developer views, labeled speed 137 / empty gripper. Each click selects the matching endpoint, creates a separate attempt record, and executes one direction with existing checks. An interrupted attempt blocks another button run; no automatic approach or repeat.
- Added developer-only coactive correction capture for Descend/Grip, using hand-demonstrated stationary measurements only. Accepted preferences update the reference for the next explicitly requested stage and are included in Haiku context. Originals, rejected corrections and measured outcomes persist; no model-weight training or automatic movement.
- No approved pickup reference currently exists: Developer must review a valid measured Align/Descend/Grip baseline first. No new correction was captured and no pickup/route test was commanded during implementation.
- 91 offline tests pass across the affected reference, replay and API suites. Headless browser tests pass for both route views and developer capture/accept; researcher learning controls are absent. [Workflow instructions](../../COACTIVE_PICKUP.md).

## Saved Home connection — offline implementation

- Return Home from Hamilton now uses the exact tested three-point departure at 137, then three queued points at speed 5 to actual saved Home (X289.97, Y62.63, Z248.02, Rz−3.88). Home-area ↔ Home uses lift to Z300, level translation with wrist adjustment, then descent; three commands each way preserve that clearance-height shape. Added Go to Home-area for its reverse.
- The Hamilton workspace exception stays bound to the reviewed route; the connector passes ordinary workspace and IK checks in both directions. Joint, telemetry, interruption and failed-attempt checks remain. No Lua republish needed.
- 76 affected offline tests and headless browser checks pass, including six-command full return, three-command reverse connector, invalid-route refusal before departure and Stop/retry handling. [Exact connector coordinates](home_connection/review.json). No new hardware movement or physical connector-clearance test performed.
- Loaded with program stopped and hand-guiding off. Read-only verification at Hamilton reports Home available with no workspace blocker; latest Hamilton replay remains available. Pose unchanged, servos disabled, program stopped, no controller errors.

## Home translation speed 137 — offline update

- User requested matching Hamilton speed. Home translations were 5, not 10. The active old-planner Home run was left uninterrupted and finished at saved Home; its speed-5 sequence snapshot is retained in `home_connection/*_speed5_baseline.json`, alongside the ongoing telemetry recording.
- Home-area ↔ Home now requests 137 through the existing Lua queue. Other Home starts combine translation into lift and level-travel/descent batches at 137; any wrist-only rotation retains its existing speed and 30-degree segment limit. The example starting near X293/Y−69/Z90 uses three translation commands plus three wrist steps, instead of dozens of short translations.
- Added a bounded Home transit profile (vertical lift, constant-yaw level travel at Z≥300, vertical descent). Full-route IK/workspace checks precede preparation; no workspace, collision, joint, telemetry or Stop protection was removed. Other route speed caps and calibration/pickup controls are unchanged. Lua 220108 is required; no republish needed if already installed.
- 121 offline tests pass, including real Lua with fake hardware, both connector directions at 137, generic Home with separate wrist rotation, invalid shapes, old firmware rejection, Stop and uncertain-command handling. [Offline candidate](home_connection/speed137_review.json). No speed-137 Home hardware run or dynamics/clearance validation performed; consistent commanded speed does not imply constant measured speed.
- Loaded after the old Home run completed. Live status reports `translation_speed: 137`; pose remains X289.97/Y62.63/Z248.02/Rz−3.88, hand-guiding off, program stopped, no controller errors. No new movement commanded.

## Direct Hamilton to true Home — 20 October 2026 (offline)

- Removed the automatic Home-area destination and detour from Home/Hamilton travel and Hamilton → Home → Squid. Historical recordings are preserved.
- Preserved the Hamilton entrance/exit and original transit until X215.74/Y-249/Z212/Rz-0.94, inside the normal workspace. From there, connect directly to true Home X289.97/Y62.63/Z248.02/Rz-3.88; reverse the same path for Home → Hamilton.
- Three queued targets instead of six; planned Hamilton-to-Home distance 595.95 mm instead of 861.39 mm. Speed 137 and zone=-1 unchanged. This is a geometry comparison, not a measured time/smoothness result.
- New connector uses the ordinary box. Only the exact inherited Hamilton prefix retains its prior box exception. IK, joint winding, gripper preservation, telemetry and Stop checks remain.
- Both-direction real-Lua/fake-hardware route tests pass, along with focused planner, Home, pickup and queue checks. A broader historical loaded-pickup suite has five failures because its 17 October baseline uses extension margin15/J4 hard205/preferred150, unlike current8/220/220; no reference or limit was changed to make it pass.
- Candidate and source hashes: [direct_true_home/candidate.json](direct_true_home/candidate.json). New connector is NOT physically validated. Confirmation displays the exact connector and requires sweep clearance before execution. No new hardware motion during this update.

## Hamilton near-zero J1 height — 20 October 2026 (offline)

- Operator requested J1=0.00 after selecting Z36.925. That earlier height was rejected: measured J1=-1.674; hardware manual page15 specifies 0–400 mm.
- Saved revised endpoint Z38.61, preserving X195.34/Y-360.31/Rz-1.90. Queue resolution is 0.01 mm, so the zero-J1 Cartesian equivalent is rounded upward: predicted J1 about +0.009 to +0.011 mm. Existing limits remain unchanged.
- Arrival, departure and station recognition use the same new endpoint; true Home remains the hub. Speed137, three queue targets, original evidence and gripper state preserved.
- Both-direction IK and 66 focused fake-hardware/planner tests pass, including below-zero start rejection and camera-calibration exclusion at the revised Hamilton station. [Candidate](direct_true_home/candidate_j1_zero_20261020.json). Automatic physical trial pending; console reload pending supported-arm confirmation.
- Loaded after explicit supported-arm confirmation; console PID26668 reconnected healthy, Manual/paused, hand-guiding off. Pose stayed Z39.14/J1+0.541 (not the new endpoint); no motion/enable/program-start sent. Lacry memory updated. Automatic physical trial remains pending.

## Hamilton near-zero J1 round trip — 20 October 2026 (hardware)

- Operator removed plate and confirmed clear route/E-stop. Added a bounded departure from up to1 mm above the endpoint (XY/yaw within0.05), allowing the actual Z39.133 start without first lowering. Exact three exit/entry targets and all joint limits retained;25 focused checks passed.
- Auto preparation closed empty jaws to approximately0. Program start initially returned error8 because servos were disabled; normal enable/start completed with no controller faults. No fault reset or motion retry. An initial recorder schema error stopped before dispatch; that failed preflight was retained.
- Lacry completed current Hamilton → true Home → Hamilton at speed137:28.12 s and27.93 s including dispatch/polling. True Home X289.970/Y62.630/Z248.021; final Hamilton X195.338/Y-360.310/Z38.609/Rz-1.900, J1+0.00994. No controller errors or gripper commands during travel.
- [Full telemetry](../../hamilton/zero_roundtrip_20261020T113048Z.json). Successful empty-gripper execution only; operator visual acceptance and loaded station handling at the revised height remain separate.

## Hamilton moved up — 26 October 2026 (proposal only)

- Saved operator-taught feedback: X144.499/Y-350.676/Z61.221/Rz-3.000; J1=22.622 mm, E1 approximately 3.806 mm. Payload is unknown. Raw status is preserved in [taught_state.json](hamilton_reteach_20261026/taught_state.json).
- [Candidate](hamilton_reteach_20261026/candidate.json) preserves true Home and both approach waypoints; only the final destination changes, rounded to queue resolution. Relative to the old endpoint: X -50.841, Y +9.634, Z +22.611 mm, yaw -1.1 degrees. Speed137 and three targets retained as proposed settings.
- Both directions pass sampled IK continuity, reach and joint checks; predicted arrival matches measured joints within 0.003 degrees. The unchanged hover creates a diagonal final descent with 51.812 mm horizontal travel. The new segment extends outside the ordinary workspace and is not covered by the old pinned route exception. Offline feasibility is not physical-clearance validation.
- No movement, runtime promotion, station-handling update, workspace change or new exception. Prior recordings and the active endpoint remain intact. The new fixture position and diagonal approach need review before executing this proposal.

## Revised Hamilton endpoint — 26 October 2026 (supervised hardware trial)

- Operator returned the arm to Home and requested the displayed proposal immediately with hands clear and E-stop supervised. Dedicated one-attempt execution binds the exact candidate SHA256, source files, unchanged Home/approach points and settings. Its narrow final-segment workspace exception does not change the ordinary workspace or production Hamilton route.
- 64 focused checks passed, including real Lua/fake hardware, exact three-target serialization at speed137, altered-route rejection, Stop and existing queue regressions. Idle console reloaded; no program restart, fault reset, gripper command or automatic retry.
- Home → revised Hamilton completed in about 8.1 seconds including queue dispatch/monitoring. Final feedback X144.500/Y-350.680/Z61.220/Rz-3.000; no reported controller errors; E1 stayed approximately3.822 mm. [Trial and telemetry](hamilton_reteach_20261026/forward_speed137_trial.json).
- Controller-confirmed completion only; operator visual acceptance pending. Reverse travel and station pickup/release at this new location have not been tested. Production station recognition still uses the prior endpoint.

## Revised Hamilton return — 26 October 2026 (supervised hardware trial)

- Operator explicitly accepted the forward placement and requested the same path back. [Acceptance](hamilton_reteach_20261026/operator_acceptance.json) retained separately from the original trial.
- Exact reversed three-target Lua path completed at speed137 in 8.230 seconds, including dispatch/monitoring. Final feedback is saved Home: X289.970/Y62.630/Z248.020/Rz-3.880. No reported controller errors; E1 remained approximately3.821 mm, with no claw command or program restart.
- [Reverse trial](hamilton_reteach_20261026/reverse_speed137_trial.json) includes 44 samples and the forward trial hash. Both directions have controller-confirmed completion; reverse visual acceptance and new station pickup/release remain untested. Production Hamilton route has not been replaced.
- Subsequent operator feedback: “Great, success.” [Reverse acceptance](hamilton_reteach_20261026/reverse_operator_acceptance.json) saved. Both travel directions are now operator-accepted at speed137 (forward8.050 s, reverse8.230 s). Production integration and pickup/release at the new endpoint remain separate work.

## Revised Hamilton route activated for Lacry — 26 October 2026

- Operator selected the accepted route for all future Hamilton travel, including Hamilton → true Home → Squid and the reverse. Active endpoint is X144.50/Y-350.68/Z61.22/Rz-3.00. Both directions preserve the exact accepted three-target route and speed137; Squid travel/approach speeds are unchanged.
- Station recognition uses the measured new joint configuration. Home returns, station transfer plans and local handling references share the new route, backed by hashes of both trials and operator acceptances. Earlier geometry/history remain intact. The old lower endpoint is no longer recognized as the current Hamilton station.
- Existing Hamilton jaw and slow-lift inspection steps remain; travel acceptance does not commission local pickup/release at this relocated station. Runtime reports accepted travel without inventing an empty/loaded payload classification.
- 116 backend checks passed, including real Lua/fake-hardware Hamilton → Home → Squid → Home → Hamilton, route integrity/limits, plate-handling plans and experiment sequencing. Console loaded; live read-only plan uses the new endpoint and current travel status is verified. No physical movement during integration; arm remains Home.
- Persistent Lacry memory now includes the accepted revision; stale current-coordinate notes were revised or archived with history retained in [memory integration](hamilton_reteach_20261026/memory_integration.json). Hamilton panel recognizes accepted travel evidence; UI cache version updated.
- Browser fixture checks passed with zero hardware calls, including enabled Hamilton handling controls using accepted-travel evidence, chat confirmations, Stop, progress and desktop/mobile layout; no JavaScript errors.
