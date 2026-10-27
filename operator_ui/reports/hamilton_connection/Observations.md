# Hamilton instrument observations

## 2026-10-25: next Lacry UI calibration recording armed

The operator requested a new run from Lacry's browser UI, recording moves and
handshakes. Before allowing the new calibration, a read-only review confirmed the
prior operation was finished, Idle, parked, empty and had no pending errors. Its
`finished_unverified` ownership marker was archived, retaining that outcome and
without creating a Pass. See
`../hamilton_api/polling_20261025T080235Z_4e315de3/review_for_authorized_retry.json`.

Capture `lacry_ui_capture_20261025T084214Z` is armed for the next calibration.
During execution it watches local Lacry journals only. After a terminal outcome
and native Idle it collects paged native traces, API request/response handshakes,
events and a chronological command list. It sends no hardware writes or dialog
answers. Its window is two hours; native logs are not continuous encoder telemetry
and cannot establish HTTP calls made by unrelated clients. The recorder's
`status.json` records armed/running/completed state and any coverage limitations.

While preparing this run, fixed a UI bug where every typed Yes was intercepted as
a plan-start confirmation even when answering a setup question before a plan
existed. Questions now have bound response buttons; their answers retain context
and can lead to a plan, but cannot start an undisplayed plan. Known Hamilton full
calibration requests should directly produce the two-stage plan with requirements.
The proposed full calibration remains waiting for the operator in the UI; no new
calibration has been started by this setup work.

## 2026-10-25: reduced polling, mostly successful physical calibration, missing final result

The operator described this as a mostly successful run. Reduced polling was enabled by default for Lacry's self-calibration, channel calibration and full-calibration actions. The default full-calibration attempt completed self-calibration and advanced to the channel stage. Channel selection exposed two rejected identifier formats before the correct catalog database ID, string `"273"`, was accepted by `calibration/close-labware-view`. The part/reference number `235903` and exported document GUID are not accepted for that field on this installed API. The start request still uses numeric `tipLabwareId: 273`.

The subsequent channel trial used the operator-confirmed full 300 µL framed conductive filtered rack at site 7, lid removed, door closed, hands clear. Camera validation passed. The native channel routine performed squeeze calibration for both channels, tip-height calibration and dispenser calibration. The trace records squeeze results 360 and 320 and Z-tip-height results -1.18972492 and -1.13964558. These are returned native values, not manually supplied geometry or acceptance thresholds. The operator observed channel movement. No new instrument errors were reported during this run.

Two apparent freezes were missing API lifecycle acknowledgements. `Loads/ShowDialog` required `POST calibration/begin-load`, waiting for `PrepareLoadingFinished`, then `POST calibration/end-load`. This released the loading dialog and started Calibrate. After calibration, `Unloads/ShowDialog` required `POST calibration/begin-cleanup`. A fresh check verified parked heads and no attached tips; the operator then removed the site-7 rack and confirmed door closed/hands clear. `POST calibration/end-cleanup` released unloading. Hamilton emitted `finished` and returned Idle. These acknowledgements were recorded in one-shot helper logs during the live test.

**Result limitation:** Hamilton did not publish a new channel result. The latest returned Pass remained pre-existing record 3009. Its touchscreen continued showing an old tool-not-detected popup rather than a new Finish screen. Therefore this is recorded as **finished_unverified**, not a newly verified Pass or an uninterrupted successful full-calibration chain. The native calibration activity ended; absence of new errors alone is insufficient to certify its result. The unresolved ownership marker was retained for review. The stale host monitor was replaced only after verifying native finished, Idle, parked, no tips and no pending errors; no extra abort or new calibration was sent.

Lacry integration now uses reduced polling automatically. A single worker retains critical run/error/result checks and event subscriptions; background UI queries use its snapshot, camera refreshes and nonessential device queries pause, and normal polling resumes after the run. Original door/enclosure checks remain. The observed loading handshake is integrated under the already confirmed rack setup. Unloading appears in chat with **Finish unloading**; the operator response sends `end-cleanup` after a fresh door check. Duplicate events/clicks cannot repeat writes. A native finished/Idle state without fresh result evidence now ends monitoring as unverified rather than waiting indefinitely. This state is displayed after restart and blocks new starts pending review.

The earlier reduced-polling self-calibration success and normal-polling failure support a polling interaction, but do not prove GenericBusy means request overload or identify one offending query. The channel test also corrected lifecycle bugs, so it is not an isolated polling-only comparison. The newly integrated automatic lifecycle was verified offline; this live run used recorded acknowledgements and was not repeated after reloading.

Validation: 74 distinct relevant unit tests passed across the Prep, polling, touchscreen, workflow and calibration-lifecycle suites (shared Prep tests were also repeated by discovery). The fixture-only Edge browser test passed with zero hardware calls: it verified camera polling pause/resume and visible **Finish unloading**, no acknowledgment before the click, and one response despite a double-click. Backend tests verify native begin/end cleanup order, physical confirmation, fresh closed-door check, and rejection of unparked unloading. The deployed backend was reloaded and read-only checks confirmed automatic reduced polling configured, normal polling restored outside calibration, the preserved unverified operation visible, Hamilton Idle/parked, and no host sequence active.

Evidence: [initial polling comparison](polling_comparison_result_20261025.json), [default full-calibration request log](../hamilton_api/polling_20261025T074825Z_7b9243ac/requests.jsonl), [channel trial journal](../hamilton_api/731faefc2a214375916c3a4825f47c00.jsonl), [request log](../hamilton_api/polling_20261025T080235Z_4e315de3/requests.jsonl), [native calibration trace](../hamilton_api/polling_20261025T080235Z_4e315de3/stall_diagnostic_snapshot.json), [terminal review](../hamilton_api/polling_20261025T080235Z_4e315de3/finished_unverified_review.json), and the `loading_*` / `cleanup_*` files in that trial folder. Controller timestamps are approximately 50 minutes behind workstation UTC; preserve both clocks.

## Full calibration verified; native two-channel pickup and waste ejection succeeded

On 2026-10-25 the operator reported completing both Self-Calibration and Channels calibration on the touchscreen, and observing successful tip attachment during calibration. Read-only audit confirms MlPrep Self Calibration completed, followed by MlPrep Height and Squeeze Calibration completed. Channel result 1008 is Pass, hasError=false, with no warnings and valid Z offsets for both channels. It is the first successful channel-calibration entry in the ten returned history records; earlier self-calibration had already succeeded, so this is not the first-ever successful self-calibration. The exported channel-calibration-results.log independently records result 1008 as Success. Server timestamps remain approximately 50 minutes behind workstation UTC; retain receipt timestamps separately.

Compared with the pre-calibration export from coordinate_probe_20261025T024959Z, calibration changed IndependentOffsetX, both Y/Z offsets, squeeze positions (index 1: 340 to 320; index 0: 380 to 360), dispenser return distances, and ZTipHeight (index 1: 0.7283356 to -0.7248504; index 0: 0.6604035 to -0.7427337). These are saved controller calibration values, not manually applied pickup offsets. Evidence is in post_calibration_reference/calibration_comparison.json and calibration_export.zip.

Operator corrected the rack location to SITE 7 before any test command was sent. A fresh image and deck scan confirmed a tip rack there; expected catalog 273 was the best match (confidence 0.908), while site 4 was empty. Original Hamilton pedestal and compatible 300 uL rack remain the operator-reported configuration. Preflight confirmed PRPGD2427, Initialized, Idle, parked, original door closed/enclosure present, no attached tips, no active workflows, and no pending errors.

Sent exactly one PUT diagnostics/instrument/tip-pickup at workstation UTC 2026-10-25T03:31:03.585712, payload TwoChannel / tipLabwareId 273 / deckPosition 7 / ejectToWaste true. Used the native catalog geometry and calibrated controller settings; no camera-derived motion offsets or extra descent were applied. Both sleeve sensors became true at 03:31:27 and false at 03:31:35, with further attached/empty transitions during the native diagnostic's multiple pairs. No start retry or abort was sent. Final traces explicitly report Tip_Pickup_Test_2_Channel complete, assay complete, and Execution completed. Independent verification after 03:32:20 confirms Idle, parked=true, has-tips=false, both sleeve sensors false, door/enclosure true, no pending errors, and unchanged historical error count 152. This is a successful pickup and ejection-to-waste test, not a re-rack test or liquid-transfer validation.

The original monitoring helper stopped after its short observation window and encountered HTTP 400 on a status read while the diagnostic was still running. Continued with a separate read-only monitor until terminal Idle and verified completion traces. Intermittent sensor-status HTTP 400 responses during movement are a monitoring limitation; they did not represent a failed start, trigger a retry, or produce an instrument error.

Operational lesson: establish and verify successful full commissioning calibration, including Channels height/squeeze calibration, before troubleshooting pickup geometry or attempting deeper descent. Self-calibration alone is not equivalent to successful channel calibration. Preserve these successful calibration values and use a native pickup/ejection test as the baseline. This does not establish a requirement to rerun full calibration before every experiment, nor isolate calibration as the sole cause because rack site and setup also changed. Previous camera-coordinate plans must be regenerated and validated after changed calibration; do not replay old plans.

Evidence: post_calibration_audit.json; post_calibration_reference/ (camera, scan, calibration export/comparison); core_pickup_20261025T033102Z.jsonl; post_calibration_pickup_monitor.jsonl; post_calibration_pickup_final.json.

## Channels moved above configured waste for operator touchscreen calibration

Operator requested moving the channels to waste and taking over self-calibration on the touchscreen. Current native MlPrepSelfCalibration was waiting at Close Door; sent one calibration/abort and confirmed Idle before direct movement. Fresh probe coordinate_probe_20261025T025955Z confirmed no tips, both channels at upper clearance, and controller waste sites 1/2 at X=286.8, Y=10/30. Used those XY coordinates with Z=165.5 (not the lower waste-ejection height). A single coordinated high-clearance move completed at local UTC 2026-10-25T03:00:19 with direct original-interlock monitoring; readback front (286.80249,9.99356,165.49651), rear (286.80249,30.01921,165.49648). No pickup, ejection, or calibration was performed in this move. Final API state Idle, no tips and no pending errors. Operator may now start the touchscreen routine; do not start another agent-controlled calibration concurrently. Evidence: waste_clearance_plan.json and pickup_journal.jsonl in that probe directory.

## Original pedestal reference test and native attachment-calibration investigation

Follow-up: operator saw only the previous pickup error on the touchscreen, not the calibration's tip-selection dialog. At local UTC 02:53:22 the prior pickup error group and its channel errors became handled; the calibration then emitted aborted/Idle/abortcompleted without a result. The initial helper unnecessarily called calibration/abort again after receiving the terminal aborted event. Corrected that helper to avoid aborting already-aborted or Idle workflows. Two subsequent API starts (02:54:49 and 02:55:30) canceled during scheduling before new tip-selection or calibration movement. The last attempt sent no redundant abort. Do not claim this cleanup fix resolves the pickup failure or proves the cause of scheduling cancellation. Stopped API retries and asked operator to launch the documented Channels calibration from the touchscreen; monitoring continues separately. The exported .mlplre identifies catalog 273's ReferenceLabwareId as string "235903", which is the prepared close-labware-view selection, but no such reply was sent because the restarts aborted before presenting a new selection view.

Operator confirmed an original Hamilton pedestal was available, then confirmed it installed at site 4 with the 235938 rack seated, lid removed, door closed, hands/arm clear. Camera capture coordinate_probe_20261025T024959Z shows a full rack at site 4. Native deck scan matched tip racks, including catalog 273 (300 uL framed conductive filtered). Sent one native diagnostic at local UTC 2026-10-25T02:50:20: TwoChannel, tipLabwareId 273, deckPosition 4, ejectToWaste true. No camera-derived pickup offsets were used.

The live event stream reported both front and rear channels did not detect the expected tip type. Neither sleeve sensor confirmed attachment. Sent one protocol-run/abort; received aborted, Idle and abortcompleted events. Final snapshot confirms Idle, no tips, no pending errors, not parked (both Z home). This establishes failure also occurs on the operator-reported original pedestal through the native diagnostic; it does not prove a particular mechanical or calibration root cause. Journal: core_pickup_20261025T025019Z.jsonl; final API snapshot: original_pedestal_native_final.json.

The internal PC clock is approximately 50 minutes 15 seconds behind this workstation: at local UTC 02:51:37 the HTTP Date header was 02:01:22. Thus current native trace/error timestamps around 02:00 are not necessarily stale; correlate them with receipt times and run events. No clock settings were changed.

Channel-results contains five old failures, most recent 2026-08-31, reporting front-channel motor stall. Operator explicitly states these were due to insufficient grease and were repaired previously. Treat them as resolved historical faults, not the current diagnosis. The earlier successful self-calibration is distinct from channel height/squeeze calibration.

Started native POST calibration/channel-height-squeeze at local UTC 02:52:12 with tipLabwareId 273 and tipLabwareSite 4, using existing saved calibration export as baseline. It presented a tiprack selection dialog (889960fcbbcd455aa2340d3094d5a58a), text "Select tip labware and place on the deck", rather than immediately using the supplied selection. Requested operator select the actual catalog rack and site 4 on the touchscreen; the returned labwarePosition was 7, so no guessed dialog payload or automatic acknowledgment was sent. Completion/outcome must be recorded separately; this paragraph is not a success claim.

## Seek start lowered 1 mm: same tip-type error, recovered to park

Operator requested a lower Z trial. Earlier native Hamilton traces in pickup_abort_traces.json use seating Z=58.97 and seek Z=70.97 (12 mm spacing), versus the driver's default 13 mm spacing. Those native attempts also failed and are not validated successful geometry. Native exceptions explicitly identify FrontChannel:IChannel,PickupTip and "Wrong type of tip detected" for 0x0001.0x00EE.0x0100:0x01,0x0001,0x0F0A. Read-only calibration/hardware values were saved in readonly_pickup_calibration_audit.json; no calibration was changed.

Tested z_seek_offset=-1 mm, retaining seating Z=rim-8, seek speed 3 mm/s, pickup Z scale 1, clearance X scale 10 and original interlocks. Two planning captures failed because neither selected pair had both rims detected; no motion occurred from those captures. Inspected the image and added column 4 rows 1/4 as a neighboring candidate within the unchanged site-4 region and 27 mm spacing; both must still be observed and pass all existing quality/reference checks. No detection threshold was relaxed.

Fresh accepted capture coordinate_probe_20261025T023759Z selected column 4 rows 1/4. Front opening estimate (46.983888,21.602685,66.342097), seating Z=58.3421, seek Z=70.3421. The sole front pickup at 02:38:10.95Z returned the same exact 0x0F0A at 02:38:23.83Z. Abort acknowledged, rear pickup not sent, neither tip detected. Fresh stopped readback was (46.979507,21.615387,69.044205), about 2.702 mm above estimated rim and 1.298 mm below seek start. Prior trials stopped about 3.70 mm above their estimated rims: the changed seek start shifted the stopping height, but did not resolve pickup. Different neighboring tips and camera uncertainty prevent treating this as a calibrated physical-contact comparison.

Fresh preflight and recovery in coordinate_probe_20261025T023838Z retracted vertically then returned continuously to park, finishing 02:38:48Z. Both Z=165.4965, X=289.2955, front Y=344.9891, rear Y=365.0148; no tips/pending errors, door/enclosure true. Restored observed X/Z scales 2/1. Independent final state is saved in lower_seek_final_status.json. Seating/contact reference remains unresolved; no arbitrary deeper seating offset or firmware tip-check override was applied.

Evidence: [trial plan](coordinate_probe_20261025T023759Z/pickup_plan.json), [trial journal](coordinate_probe_20261025T023759Z/pickup_journal.jsonl), [stopped state](coordinate_probe_20261025T023829Z/probe.json), [recovery journal](coordinate_probe_20261025T023838Z/pickup_journal.jsonl).

## Slower Z-only pickup trial: same error, then verified parked

Operator requested slower descent and clarified "no not x y speed, only z". Retained the already tested continuous approach/return X travel scale 10 and normal pickup X scale 2. Changed pickup Z scale from 2 to 1 and the explicit seating seek speed from 15 to 3 mm/s; no force, depth, type-definition or interlock change. These are commanded settings; no independent instantaneous Z-velocity measurement is claimed.

One front-channel pickup was sent at 2026-10-25T02:28:32.74Z using the freshly observed column 4 row 3 opening, estimate (47.103276,39.630143,66.347859), seat Z=58.3479, seek Z=71.3479 and stored 300uL StdVolFilter ID 2. It again returned the exact 0x0F0A entry (1,238,256), interface 1/action 1, source-table meaning "Wrong type of tip detected." Monitoring remained responsive. Abort was acknowledged; no rear pickup or automatic retry followed. Neither channel sensed a tip. The interrupted assistant turn did not terminate the running script; its completed output was recovered when the operator asked for status.

Read-only verification found front stopped at (47.105507,39.626892,70.052597), rear (47.105507,66.644165,165.496475). Completed the previously requested return to park after a separate fresh preflight: vertical retraction, then continuous faster XY return. Final status at approximately 02:29:17Z is Idle, is-parked=true, has-tips=false, no pending API errors; original door/enclosure true. Final front position (289.304474,344.989136,165.496506), rear (289.304474,365.014771,165.496475). Recovery restored its observed starting X/Z scales 2/1. Slowing descent did not resolve this trial's tip-type detection error; this alone does not identify the underlying cause.

Evidence: [slow-trial plan](coordinate_probe_20261025T022822Z/pickup_plan.json), [trial journal](coordinate_probe_20261025T022822Z/pickup_journal.jsonl), [stopped state](coordinate_probe_20261025T022857Z/probe.json), [final parked status](slower_z_final_status.json).

## Faster continuous approach tested; repeat tip-type error; returned to park

Operator requested inspecting alignment, another pickup, and faster approach/return to park. Compared the two earlier pre-pickup camera estimates: front opening XY changed (-0.0219,-0.0130) mm, rear (+0.0044,-0.0121) mm. Last stopped front encoder XY differed from its estimated target by (+0.0020,-0.0156) mm. The magnified raw image shows no obvious gross rack displacement, but the nozzle hides the mating point. These comparisons establish tracking/repeatability relative to the camera estimate, not calibrated physical centering or correct seating height.

Increased only the high-clearance X travel scale from 2 to 10; retained X/Z=2/2 during pickup and the same standard seek speed 15 mm/s. Added bounded CLI travel-scale selection, optional successful return to park, and encoder-settling checks after coordinated moves. Generalized recovery to require a named stopped-position probe, unchanged live positions, a narrow reviewed rack region, no tips/errors and original interlocks. Vertical retraction precedes horizontal motion. A preliminary continuous clearance move took about 4.4 seconds versus about 20.6 seconds at scale 2.

Three planning captures did not all meet the existing vision checks (one fixed-post detection failure, others missing individual rim detections); none sent pickup/motion. The 02:25:02Z capture had a valid fixed-post check (0.541 mm) and directly observed image-grid column 4 rows 2 and 5. Added selection of that neighboring pair when rows 3 and 6 are not both observed; neither pair uses inferred rims. The accepted image was approximately 61 seconds old at execution, inside the unchanged 180-second limit; live start positions and door/enclosure were rechecked, with no intervening rack motion command. No vision quality threshold was relaxed.

Executed one new front pickup at 02:26:10.67Z, using opening (46.975288,30.792477,66.497285), seat Z=58.4973, seek Z=71.4973, stored tip definition 2. The single continuous approach including settling took about 4.9 seconds. The controller again returned the exact 0x0F0A entry at (1,238,256), interface 1, action 1: source-table text "Wrong type of tip detected." Monitoring stayed responsive; one abort was acknowledged. Rear pickup was not sent; no tips were detected. Front stopped at (46.979507,30.783203,70.192062), rear Z=165.496475. This error also occurred at the neighboring tip; no arbitrary deeper offset or tip-type substitution was applied.

Performed a separate verified recovery per the requested return to park: fresh post-error status/positions, then straight vertical retraction and one faster high-clearance return. It completed at 02:26:39Z. Final independent probe at 02:26:53Z reports Initialized, Idle, is-parked=true, has-tips=false, no pending API errors, door/enclosure true; coordinates front (289.304474,344.989136,165.496506), rear (289.304474,365.014771,165.496475). Temporary speeds restored to their pre-run 2/2 values. Do not carry forward the previous notes saying the head remains low/unparked.

Post-return camera fit used 71 rims; rack center estimate differed from the pre-attempt fit by (+0.087,-0.125,-0.288) mm. This does not indicate a gross rack shift; fit uncertainty and camera bias remain. Tip detection and the seating-height convention still require investigation before changing contact geometry. Evidence: [trial plan/journal](coordinate_probe_20261025T022502Z/pickup_plan.json), [stopped state](coordinate_probe_20261025T022620Z/probe.json), [final parked state](coordinate_probe_20261025T022653Z/probe.json), [rack comparison](coordinate_probe_20261025T022653Z/rack_alignment_comparison.json).

## Continuous-approach retry reached a controller tip-type error

Operator observed that the previous approach aligned nicely, explicitly requested another pickup and asked to eliminate the segmented zig-zag approach. Verified the stopped positions were unchanged and the instrument remained Initialized/Idle with no tips. An HTTP 400 is a server response, not proof of an Ethernet disconnect; the prior failure's exact HTTP body is unavailable. A trace query returned older records and did not establish the previous failure's cause.

Discovered the live controller's named GetIsDoorClosed method: MLPrepRoot.MLPrep, interface 1, method 22, empty request -> bool. Verified its signature alongside GetIsEnclosurePresent (method 21), and five read-only pairs returned true/true. Added prep_door_monitor.py and changed the pickup runner to use these two original-interlock reads on a dedicated third TCP connection during motion. A separate connection remains reserved for abort. No safety setting or interlock override was changed. HTTP composite sensor-status remains a stationary preflight/postflight check; it is no longer polled while the pickup moves. Offline checks confirmed open/unknown door, absent enclosure and monitoring timeout are all rejected. The direct monitor worked throughout the actual recovery and retry.

At 2026-10-25T02:17:40Z, retracted front vertically from Z=69.7200 to 165.5 with XY unchanged, then sent one coordinated high-clearance move to the camera-clear position. Both completed. Changed the approach plan from many <=10 mm commands to clearance normalization plus ONE coordinated XY command at Z=165.5, using the front opening's exact X. The existing region, bounds and fixed-post checks remain; no low-clearance horizontal travel is allowed.

Fresh retry evidence is coordinate_probe_20261025T021811Z. The single continuous XY approach ran from 02:18:17.46 to 02:18:38.01Z, ending front near (47.0335,39.9510,165.4965), rear Y=66.9683. Sent one front-only PickUpTipsById using stored definition 2 (300uL StdVolFilter), opening estimate (47.06746,39.96664,66.71429), seating Z=58.7143, seek Z=71.7143, final Z=165.5, standard seek speed 15 mm/s. Direct interlock monitoring stayed responsive and true. This time the command returned a ChannelizedError, not a monitor/network failure: HcResult entry module 1, node 238 (0xEE), object 256 (0x0100), interface 1, action 1, result 3850 (0x0F0A). The pinned PyLabRobot error table maps that exact address/interface/code to "Wrong type of tip detected." Live enum-text introspection returned null, so attribution is to that source table, not a firmware-provided text string. The error is associated with the sole requested front pickup; the driver error-map index does not mean a rear pickup was requested.

Issued one acknowledged MethodAbort and stopped before rear pickup. No extra insertion, type change, force change or automatic retry. Neither sleeve sensor reports a tip. Post-fault readback at 02:18:49Z: front (47.069508,39.951019,70.417343), rear (47.069508,66.968277,165.496475). Initialized/Idle, door and enclosure true, has-tips=false, no pending HTTP errors. Heads remain unparked with front near the rack; X/Z scales remain 2/2, as at the beginning of this retry. The observed type-detection error does not alone prove the physical tips are the wrong catalog part or identify an alignment/seating fault. Do not bypass that check; investigate before another attempt.

Evidence: [retry plan](coordinate_probe_20261025T021811Z/pickup_plan.json), [retry journal](coordinate_probe_20261025T021811Z/pickup_journal.jsonl), [decoded error](coordinate_probe_20261025T021811Z/error_detail.json), [stopped state](coordinate_probe_20261025T021849Z/probe.json). Updated exception logging to retain str(error), since repr(ChannelizedError) omitted its detailed payload.

## Camera-aligned pickup attempted; aborted after HTTP monitoring failure

At the operator's explicit request, "Attempt pick up", prepared one sequential two-tip trial at site 4. No calibration or interlock setting was changed. The starting hover obscured/shadowed the rack: the current image passed too few rim detections. Raised both bare channels vertically to Z=165.5, then moved aside at that height in <=10 mm coordinate increments. Repeated the read-only capture after the camera image settled; no vision threshold was relaxed. Those clearance motions completed with position readbacks and original door/enclosure checks.

Read the controller's stored tip definitions. Definition ID 2 is "300uL StdVolFilter", filter=true, standard-volume type, effective length 51.9000015 mm and firmware capacity 360 uL. This matches the pinned PyLabRobot 235938/235903 300 uL filtered tip creator (physical length 59.9 mm, fitting depth/collar 8 mm). Nominal user-facing volume remains 300 uL. Source TipPositionParameters.for_op defines the pickup target at the collar-rest plane and seek at collar-rest+8+5 mm. Thus the trial used camera rim minus 8 mm for seating and rim plus 5 mm for seek, not a guessed deeper jog.

Fresh execution capture 2026-10-25T02:13:00Z fit 72 rims, pose RMS 1.541 pixels, and fixed-post approximate frame discrepancy 0.473 mm. Selected observed image-grid column 4 rows 3 and 6. Front opening estimate (47.08933,39.97961,66.70363), rear (47.22293,66.97245,67.31119). These remain experimental camera estimates; this attempt does not establish a validated contact calibration. Sequential commands avoid averaging their different X targets. Offline checks verified single-channel encoding, the collar/seek datum (accounting for Coordinate's four-decimal rounding), and full-clearance XY travel.

At 02:13:44.875Z, sent exactly one PrepPickUpTipsById command for firmware channel 1 (front), ID 2, X=47.0893, Y=39.9796, seating Z=58.7036, seek Z=71.7036, final Z=165.5, standard seek speed 15 mm/s, no liquid and no TADM. X/Z speed scales were temporarily set from 100/100 to 2/2. The command began descending. During it, the independent HTTP GET service-software-api/sensor-status returned HTTP 400. The runner stopped on the monitoring failure and issued MethodAbort through the separate TCP connection at 02:13:46.126Z; acknowledgment arrived at 02:13:48.182Z. The outer error handler issued a second acknowledged abort. The pickup response was not confirmed before cancellation. No second-channel pickup, automatic retry, deeper descent or recovery motion followed.

Post-abort read-only capture at 02:13:54Z reports Initialized, Idle, original door closed, both sleeve sensors false, has-tips=false and no pending HTTP API errors. Front stopped at (47.087505,39.997314,69.720047); rear at (47.087505,66.968277,165.496475). Heads are NOT parked; front is near the rack. Speed scales were intentionally not restored after the uncertain pickup outcome; last requested values remain 2/2. Abort was acknowledged and motion is stopped, but this is not a successful pickup or a demonstrated mechanical pickup failure. The HTTP 400 body was not retained, so its exact cause is unknown. Fix/verify reliable monitoring during a pickup before another trial; do not remove monitoring or replay this command blindly.

Evidence: [pickup plan](coordinate_probe_20261025T021300Z/pickup_plan.json), [command/abort journal](coordinate_probe_20261025T021300Z/pickup_journal.jsonl), [post-abort read-only state](coordinate_probe_20261025T021354Z/probe.json). Executable trial is run_camera_pickup_trial.py, with an explicit --execute-authorized entry point and no retry path.

## Camera-based high-clearance alignment completed at site 4

The operator accepted using the camera's internal-coordinate estimate and explicitly requested dynamic alignment of the heads to the tip rack at site 4. Prepared a bounded commissioning trial rather than changing the camera registration's contact-validation flag. Projected the controller's fixed calibration post (129.10,184.40; 6 by 6 mm; top Z=22.10) through the exported camera model. Its projected location matches the visible post; bright-post centroid differs by about 0.48 mm. This independently supports approximate common-frame use for a high-clearance approach, not precision tip insertion or a full 3-D registration.

Added `hamilton_hover_alignment.py` and `run_camera_hover_trial.py`. The planner requires both channel limits, a high parked start, visible central tip openings, fixed-post agreement <=1 mm, at least 15 mm channel separation, targets within reported limits, and Z>=130 mm throughout. XY travel and final descent are separate; each step changes each axis by at most 10 mm. The runner allows only named coordinated moves, status queries, method lifecycle and reversible X/Z speed scales. It cannot initialize, calibrate, issue raw drive moves, pick up tips, or override the door. The current run's authorization covers this high-clearance trial. Five offline tests passed before execution.

Fresh vision selected image-grid column 4, rows 3 and 6 (zero-based image indices, not vendor well labels); earlier proposed column 5 openings were intermittently not detected and were not assumed present. Both selected openings were observed. Planned common hover X=46.99 mm, front Y=39.59936, rear Y=66.59482. Their small X difference is acceptable for this approximate hover only; it is not automatically accepted for simultaneous tip pickup.

Executed one authorized trial at 2026-10-25T01:59:48Z through PyLabRobot's standard Pipettor.MoveToPosition. Original sensor preflight showed door closed, enclosure present, initialized, no tips/errors or active workflows. Started a method with automatic_pause=true; saved X/Z speed scales (100/100), temporarily requested 2/2. First normalized both high Z positions to 165.50; readbacks were 165.4965 for each, showing both channels can reach the same in-range height despite the earlier differing home positions. This does not by itself explain the home-position/limit discrepancy.

All 36 coordinated movements completed and passed readback tolerance of 0.2 mm on every axis. Travel finished at high Z before descending in four steps to Z=130. Final positions independently re-read after closing the motion connection:

- Front (firmware channel 1): X=46.98851, Y=39.58060, Z=129.99870 mm.
- Rear (firmware channel 2): X=46.98851, Y=66.59785, Z=129.99870 mm.

Final coordinate errors versus commands are under 0.02 mm, which establishes commanded positioning accuracy, not nozzle-to-opening physical centering. MethodEnd and restoring X/Z scales to 100/100 were acknowledged. Final HTTP status is Initialized, Idle, door closed, no tips, no pending errors, no running workflows, and parked=false. Heads are intentionally left hovering above the rack. No tip insertion or pickup occurred. No interlock settings or calibration changed. Door stayed closed throughout; no real door-open interruption or abort fault was induced, so those behaviors are not claimed as physically tested.

The post-trial camera shows the heads over site 4. Projected reported coordinates lie near the visible rear coupling; part of the front coupling is obscured by the mechanism. The high camera angle and occlusion do not independently confirm both coupling centers to pickup precision. Current hover is roughly 63 mm above the camera-estimated opening plane. Further descent/contact requires additional centering and seating validation rather than treating the successful hover as a successful pickup.

Evidence: [executed plan](coordinate_probe_20261025T015942Z/hover_plan.json), [command/response and sensor journal](coordinate_probe_20261025T015942Z/hover_journal.jsonl), [independent final readback](coordinate_probe_20261025T020039Z/probe.json), [post-trial camera](coordinate_probe_20261025T020039Z/hover_camera.jpg), [reported-coordinate projection](coordinate_probe_20261025T020039Z/hover_projection.jpg). The runner's cleanup was subsequently hardened to close both connections even if profile restoration fails; no further movement was run for that edit.

## PyLabRobot direct connection verified; dynamic alignment preview implemented

Following the operator's request to use PyHamilton/PyLabRobot for dynamic alignment, checked the [PyHamilton README](https://github.com/dgretton/pyhamilton): it documents STAR/STARlet and VANTAGE support, not Prep. Found the newer Prep driver in current PyLabRobot main and its [getting-started documentation](https://docs.pylabrobot.org/dev/user_guide/00_liquid-handling/hamilton-prep/prep_basic_demo.html). Pinned local checkout to `fc5ae129c39ef645a2a11234dce97f933a317a9c`. This supersedes the earlier PR-928 source audit; that PR's closed/unmerged status does not describe today's main branch.

Added `probe_prep_coordinates.py`, with an explicit allowlist of typed status queries. It invokes transport-only open/close, never high-level PrepDriver.setup/stop. The current TCP client does not automatically reconnect/replay commands. Current high-level setup can initialize, raise channels and change speed settings; even skip_device_initialization does not make it read-only. No high-level setup, safety-setting write, motor command, calibration write, tip pickup or interlock modification was sent.

Two live probes succeeded through `192.168.100.102:2000`. Controller reports Initialized. Front (firmware channel 1) position approximately (289.3045,344.9891,165.6038); rear (channel 2) (289.3045,365.0148,167.5025) mm. Both queries report X limits 0.7825..299.7825, Z limits 18.2..165.6; front Y -9..376 and rear Y 0..385. Default traverse height 165.6. Rear current Z exceeds the returned upper limit by approximately 1.90 mm; this unresolved discrepancy must not be silently clamped or treated as a known calibration correction. Enclosure present; GetSafeSpeedsEnabled false, reported only, unchanged. HTTP before/after remains PRPGD2427, Initialized, Idle, parked, door closed, no tips and no pending errors. Direct-controller readings have now been verified on this unit, unlike the earlier reachability-only test.

Added `hamilton_dynamic_alignment.py` for rigid registration from independently measured 3-D reference pairs, held-out validation, instrument/calibration identity binding, stale-capture checks and two-opening previews. It has no hardware-write path and cannot authorize motion. Changed the offline camera estimator to export all 96 fitted grid locations, distinguish observed versus inferred openings, and render an annotated preview. Added `refresh_alignment_preview.py` to run fresh camera/status capture, TCP readings and offline estimation together. The two blue circles are review selections in image-grid coordinates, not confirmed A1 labels or executable pickup targets. The tip rack itself at site 4 provides the pickup reference; the separate plate remains at site 8. Shared X requires considering sequential pickup when two detected targets differ in X; averaging them is not assumed valid.

Latest capture at 2026-10-25T01:46:47Z detected 73 rim candidates. The preview was generated at capture age 4.39 seconds. Two selected openings are observed; their estimated exported-frame positions are approximately (55.921,30.585,66.354) and (56.056,57.584,66.534) mm. These are NOT controller targets. Camera-frame height remains around 66 mm versus the operator's 75 mm physical metal-to-opening measurement. No camera-to-controller reference registration has been physically validated; no seating depth has been inferred. Direct-driver stop and original interlock behavior still require commissioning. The preview therefore explicitly returns executable=false and controller_opening_targets=null. No dynamic hardware alignment or successful pickup is claimed.

Validation: six offline registration tests passed, covering known rotation/translation, reversed handedness, incorrect held-out references, changed camera identity, unvalidated fits and insufficient 3-D reference coverage. All four changed/new pipeline scripts passed syntax checks. The live read-only pipeline completed twice and left reported positions unchanged.

Evidence: [first live TCP probe](coordinate_probe_20261025T014322Z/probe.json), [latest probe](coordinate_probe_20261025T014647Z/probe.json), [alignment preview image](coordinate_probe_20261025T014647Z/alignment_preview.png), [non-executable preview](coordinate_probe_20261025T014647Z/alignment_plan_preview.json). The next required work is independent camera/controller reference verification and direct-driver motion commissioning, not another blind deeper pickup.

## Direct-controller jogging route found: PyLabRobot Prep TCP backend

Investigated the operator's request to find a real jog interface. PyLabRobot PR [407](https://github.com/PyLabRobot/pylabrobot/pull/407) describes full XYZ manual channel movement; its successor [928](https://github.com/PyLabRobot/pylabrobot/pull/928) contains concrete positioning implementations. Checked out PR 928 head at commit `e545f5ba28d3bc418ba1785d480fdfe3544573e2` in `operator_ui/tmp/prep-jog-audit`. The live GitHub API reports PR 928 closed and unmerged; do not describe it as an official Hamilton interface, a released feature, or commissioned on this instrument.

Source inspection confirms `PrepBackend.request_channel_positions()`, `request_channel_bounds()`, `move_channel_x/y/z()` and `move_to_position()`. The latter sends the typed Pipettor MoveToPosition command (26); position reads use GetPositions (25). Coordinates are represented as millimeters. Channel index 0 is rear, 1 is front. X is a shared gantry: moving X also moves the other channel. Relative jogging can be implemented by reading current coordinates, adding a bounded increment to one axis, and commanding the resulting absolute position. This establishes a code-level route, not successful hardware execution.

The intended transport is the controller at `192.168.100.102:2000`, separate from the normal HTTP API on the internal PC. A fresh TCP connection to that port succeeded and was immediately closed without sending any application data. No firmware handshake, introspection, position read, initialization, jog or pickup was sent during this investigation.

Commissioning constraints identified in source: high-level PrepBackend.setup can initialize automatically; use an audited transport-only path for initial read-only discovery. HamiltonTCPClient.setup performs registration and introspection, which still needs validation on this unit. Auto-reconnect may retry commands and must not blindly replay motion after an ambiguous timeout. Backend stop() only closes the connection and is NOT a verified motion-stop command. move_to_position skips validation when cached bounds are unavailable, and its local Z check omits the lower bound. A Lacry adapter must reject missing limits, validate both bounds, account for both channels and obstacles, verify an effective abort path and original door-interlock behavior, and prevent concurrent commands from the internal PC before enabling motion. No explicit door check was found in the inspected movement wrappers; firmware interlock behavior is not yet verified.

For alignment, use this route's explicit pickup geometry after establishing its coordinate reference; do not assume a jog offset survives the existing HTTP diagnostic's initialization. Current tip rack is at site 4, plate at site 8, and confirmed physical metal-to-rim height remains 75 mm. The camera frame and ruler datum are not yet proven equivalent to firmware XYZ. No Lacry jog button has been enabled and no calibration or geometry was changed.

## Full seating confirmed; fresh camera identifies rack at site 4

Operator confirms the white frame is fully seated on the recessed ledge at all four corners. Treat this as confirmed operator observation; do not keep assuming a caught rim or adjust Z from the conditional CAD discrepancy alone.

GET-only live check returned PRPGD2427, Initialized, Idle, parked true, no attached tips. The first raw frame caught the holder being held during inspection and site 3 was empty; no alignment estimate was produced for that empty crop. A subsequent stationary frame and all-eight-site camera inventory establish that the tip holder is now at site 4, with the well plate at site 8. Earlier diagnostic requests targeted site 3. This is a current deck-layout change, not proof that the earlier failures were caused by a wrong site. Any future pickup plan must be built against the current verified layout rather than reusing the previous site-3 payload.

Captured fresh site-4 crop/overlay at camera projection Z=75 and raw deck image. Offline fit used 68 tip rims with 413 registration inliers (0.290 px RMS), tip-plane reprojection RMS 1.591 px, and apparent plane tilt 0.295 degrees. Estimated center in exported frame is (60.364,43.807,65.925); the overlay-center reference at projected Z=75 is (61.948,44.474,75), yielding exploratory XY difference (-1.584,-0.668). Neither XY difference nor inferred Z is a verified nozzle target. Current appearance is nearly level; no correction, pickup, calibration write or motor command was sent.

Evidence: [status](seated_holder_camera_check/status.json), [site inventory](seated_holder_camera_check/site_inventory.jpg), [stationary deck](seated_holder_camera_check/second_preview.jpg), [site-4 overlay](seated_holder_camera_check/site4_overlay75.png), [pose estimate](seated_holder_camera_check/tip_plane_estimate.json). The offline estimator now accepts a capture directory and exits explicitly when no rim grid is detected.

## Operator base elevation: approximately 5-6 mm

The operator reports the printed holder bottom sits approximately 5-6 mm above the same metal reference used for the confirmed 75 mm tip-opening height. Subtracting gives approximately 69-70 mm from holder bottom to tip openings. That exceeds the conditional nominal seating calculation of 67.1 mm by approximately 1.9-2.9 mm. This supersedes the earlier inferred 7.9 mm base elevation; the latter was a hypothesis, not a measurement. Approximate ruler measurements, simplified vendor envelope, print error and unknown contact details prevent treating the discrepancy as an executable correction.

Re-inspected IMG_6334. It shows the rack/holder interface but does not expose all underside contact surfaces clearly enough to prove full seating. Requested checking whether the white frame's lower edge rests evenly on the recessed ledge, 4 mm below the printed upper rim, or is caught on the upper rim. No motion, deeper descent or CAD revision was sent. Measurement evidence updated in printed_holder_measurements.json.

## Printed-holder 3MF metrology and conditional seating-height reconciliation

Operator supplied C:/Users/Cephla/Downloads/hamilton_tip_pedestal_v2.3mf. Inspected the actual mesh and Bambu assembly transforms offline. The model uses millimeters, has no assembly scaling, and measures 127.76 by 85.48 by 61.5 mm. The principal upper support ledge is 57.5 mm above the model bottom, recessed 4 mm below its upper edge. Its upper pocket envelope is approximately 123.0 by 83.2 mm and centered on the model footprint. The vendor 235903 definition describes a centered frame envelope 122.4 by 82.6 by 11.6 mm. Nominal total lateral clearance is therefore 0.6 mm per axis, corresponding to up to 0.3 mm center shift on each axis if the frame is fully seated and the dimensions match the definitions. This does not include print error, tilt or movement of the entire pedestal. No designed gross lateral offset or print scaling was found.

A conditional stack calculation provides a new datum check: assuming the vendor frame's bottom/mating plane rests on the printed 57.5 mm ledge, frame origin is at 57.5+5.8=63.3 mm above the holder bottom. Its hole grid is at 63.3-4.2=59.1 mm. The vendor tip's StandardVolume_96 mating point is Z=21.95; its collar is centered at Z=25.95 and 8 mm high, giving a nominal upper opening 8 mm above the hole mating point. The resulting rim height is 67.1 mm above the holder bottom. Thus a 75 mm metal-to-rim reading would imply holder bottom roughly 7.9 mm above that same metal reference, IF this mating interpretation matches actual contact. Requested that base elevation measurement. This is a hypothesis to verify, not a revised user measurement or an executable correction. No equality between the physical metal reference and camera/instrument Z origin has been established.

This audit does not justify lowering the nozzle by 75-63 mm, changing global calibration, or claiming the custom pedestal is commissioned. The model's actual seating plane and its installed base reference are needed before a height correction. No model, instrument configuration or hardware motion was changed. Slicer settings show PLA, 100% filament shrink setting, zero XY contour/hole compensation and 0.15 mm elephant-foot compensation; they do not measure actual print error.

Evidence: [CAD measurements](holder_cad_audit/dimensions.json), [section plots](holder_cad_audit/cad_sections.png), [conditional seating schematic](holder_cad_audit/seating_height_schematic.png), [offline audit script](audit_holder_cad.py).

## Extended search for a usable alignment route

Read-only API discovery found service routine 1 named **Channel Alignment Service** and routine 2 named Camera Service. Both returned isRecommended false and lastRun null. GET service-routines/1 returns only that metadata; the API offers a start operation but no preflight requirements or detailed procedure. A separate verification/authenticate operation is described as authenticating a service password; whether the alignment routine requires that authentication was not tested. No service routine was started, no authentication attempted and no settings changed. The diagnostic-log archive contains no matching Channel Alignment/ServiceRoutine instructions.

The installed deck-position and labware-group schemas assign catalog labware to numbered sites, with no per-site XYZ correction. The labware import endpoint supports underlying definition files, while labware-signature/create concerns camera recognition and is not a pickup-offset control. Hamilton's documented custom-labware route is to request an appropriate definition from support and import it: https://www.hamiltoncompany.com/knowledge-base/faq/i-dont-see-my-labware-in-the-list-ml-prep . This provides a route for geometry changes but not a verified local authoring procedure or immediate executable correction.

Audited the already-exported 235903 rack and its T1t300FbebleHAM tip definition offline. Rack grid pitch is 9/-9 mm (12 by 8), local grid translation is (-49.5,31.5,-4.2), and its Framed mating reference is (0,0,-5.8). The tip document includes a labeled PipettingChannel/Pickup point at local Z=21.95. These local values prove that pickup geometry is represented in the definition, but are not absolute nozzle targets. The corresponding instrument/deck mating transform is absent from this export. The catalog vision height remains 63; it must not be subtracted directly from the confirmed 75 mm metal-to-tip-opening measurement to command a descent. The export includes a catalog Signature field and integrity metadata; no modified export was imported.

Requested the operator's printed-holder STL/STEP/CAD file path to audit its support seat, lateral positioning and height. No file path has yet been supplied. A mechanical correction remains conditional on establishing the target seating geometry; prior camera estimates alone do not establish a validated nozzle offset. The official Prep pedestal reference is 6600553-01 (https://www.hamiltoncompany.com/other-robotics/6600553-01).

Evidence: [live schema](alignment_live_swagger.json), [service list and status](alignment_service_capabilities.json), [alignment metadata](channel_alignment_service_details.json), [local geometry audit](alignment_geometry_audit.json). Last read-only status: Idle and parked true. No motion or calibration writes in this investigation.

## Manual positioning investigation: touchscreen menu clarification

Photo IMG_6335.jpeg resolves the Motors controls: the screen explicitly states that the selected motor moves between its upper and lower limits at default speed for two minutes or until stopped, using default acceleration when switching directions. Visible selectors include X-Axis, front/rear Y-Axis and front/rear Z-Axis. Buttons are Start, Stop and Park Instrument. These are motor-cycle diagnostics, not demonstrated direction/position/step-size controls. The preceding operator multiple-choice response suggesting positioning controls is superseded by this photographic evidence. Starting/stopping this cycle is not a verified way to teach or retain a pickup offset; do not use it as a jog substitute. No motor test or pickup was sent.

Subsequent operator correction: a Peripherals menu also exists and contains Light and Motors. The Motors entry is therefore present under Peripherals; the earlier Devices-only report was incomplete, not evidence of a missing motor interface. Requested inspecting Motors for direction/position/step-size controls versus motor selection/runtime/Start-Stop, without starting a test. Exact controls and whether any position can carry into pickup remain unverified. No movement sent.

Follow-up from the operator: Devices contains CO-RE Paddle Check, Drip Test, Pressure Test, Tip Pickup and rerack, and Tip Pickup and Waste. No Motors item or directional/step-size positioning controls were reported in that submenu. These observations do not establish the absence of a separate service interface, but the currently accessible UI/API has not yielded a manual jog control or a way to persist a corrected pickup target. No diagnostic was started in response to this menu report.

The operator reports Diagnostics contains Traces, Sensors, Vision and Devices, with no Motors entry at that level. Requested inspecting Devices without starting a test. The earlier suggested direct Diagnostics -> Motors path is not confirmed for this installation. Hamilton's troubleshooting FAQ describes Devices as the place to browse pipetting-tool and integrated-device tests, and separately lists Motors; the installed submenu structure remains to be observed.

Rechecked live Swagger: motor-diagnostics starts a motor cycle protocol and accepts only DisplayName, Motor, Channel, MphOnly and RuntimeInSeconds. It has no position, direction or step-size parameter. No supported jog endpoint or pickup-at-current-position operation has been established. Previous pickup traces start with arm initialization, so preservation of any hypothetical manual positioning cannot be assumed. No movement or calibration changes were sent. Native desktop-control helper was unavailable, preventing direct inspection of the touchscreen/remote desktop interface.

Reference: https://www.hamiltoncompany.com/knowledge-base/faq/my-ml-prep-isnt-working

## Requested dynamically aligned two-tip pickup: API capability check

The operator requested continuing to a dynamically aligned two-tip pickup. Re-fetched the installed Swagger schema directly from the instrument. TipPickupDiagnosticPutDto still exposes only ChannelSelection, TipLabwareId, DeckPosition and EjectToWaste, with additionalProperties false. TwoChannel is available as a selection, but the diagnostic has no per-request X/Y/Z correction. Schema search found offsets for aspiration/dispensing and channel calibration; these are not established pickup-position controls. No unsupported fields, aspirate offset substitution, calibration overwrite, or labware-definition mutation was attempted.

The camera estimate remains exploratory and its mapping into channel motion coordinates is unverified. Executing this requested dynamic correction requires a supported position-control interface or a validated custom labware/mounting definition, neither of which is available in the current integration. Therefore no pickup command was sent. Fresh status checks: Idle and parked true. Evidence: [live API capability check](dynamic_alignment_api_check.json).

## Confirmed physical height and exported calibration analysis

After the side photo, the operator explicitly reconfirmed 75 mm to the upper tip opening. This supersedes the rough photographic height estimate; no further physical-height change is assumed. Downloaded the read-only calibration export, which includes camera intrinsics/distortion, deck rotation/translation, calibration logs, and current channel calibration values. Contrary to the narrower camera/parameters endpoint, this export does provide camera/deck transform data.

Captured new raw, rectified, and site-3 cropped camera images. Offline registration accounts for the reflection between the deck-coordinate crop and full camera view: 619 of 680 feature matches fit with 0.234 px registration RMS. This validates image registration only, not complete mechanical calibration. Fitting a nominal 9 mm planar grid to 79 detected tip rims yielded approximately (61.18,138.84,65.98) in the exported deck frame, 1.79 px reprojection RMS, and 2.29 degrees of apparent plane tilt. These estimates depend on rim-center detection, camera calibration and transform conventions; they are not independent physical measurements.

Back-projecting the vendor overlay center at its requested Z=75 yields approximately (61.96,139.79,75). The fitted physical grid center differs by about (-0.78,-0.95) in the exported frame's X/Y coordinates. Do not apply these numbers as controller movement commands or CAD corrections yet: the exported frame's origin relative to the measured metal surface and its relationship to channel coordinates have not been verified. The inferred Z around 66 does not contradict or replace the confirmed physical height of 75; a datum difference or modeling/calibration bias remains unresolved. No geometry, calibration or motion commands were sent in this investigation.

Channel history returned older failed motor-stall calibration records, while calibration-status.json contains current channel offsets, squeeze positions, and CoreII true for both channels. Historical failures alone do not establish a present fault. No calibration values were modified.

Evidence: [offline pose estimate](camera_height_comparison/tip_plane_estimate.json), [deck calibration](camera_height_comparison/deck-calibration.json), [active calibration values](camera_height_comparison/calibration-status.json), [channel history](camera_height_comparison/calibration_details.json).

## Side-view photo IMG_6334: support arrangement and measurement uncertainty

Operator supplied C:/Users/Cephla/Downloads/IMG_6334.jpeg after the camera height comparison. The photo shows a white framed insert holding black tips, seated at the top of a printed pedestal; the printed pedestal is located between the yellow deck retainers. A tape is positioned in front of the assembly. No separate original pedestal can be positively identified beneath the printed one from this view. This clarifies the physical stack but does not validate its dimensions or locate the API height datum.

The front-row black tip openings appear nearer the tape's 8 cm region than 7.5 cm; the 7.5 cm region appears nearer the frame/support below. This is a rough visual observation only: the oblique viewpoint, ruler separation and unclear exact zero contact prevent a precise measurement. Retain 75 mm as the operator's reported value, flagged as unverified; do not replace it with an image-derived motion value. Requested a direct eye-level reading to the upper rim of a front-row black tip from the restored metal deck surface. No motion, pickup, or configuration change was sent in response to the photo.

## Camera height comparison, 25 October 2026 UTC

Continued alignment investigation using GET-only camera requests at API zHeight 60, 63, 66, 69, 72 and 75 mm. Physical rack position was not deliberately changed. Each overlay was compared with its matching plain crop using a robust regular-lattice fit to outer-rim candidates. Refined grid-boundary extraction excludes bright frame edges and handles antialiased overlay lines. All six comparisons completed; 71-77 of 84-87 rim candidates per image fit the lattice. Approximate rotation stayed below 0.3 degrees in magnitude.

| Camera projection height (mm; not pickup Z) | Column pitch mismatch | Row pitch mismatch | Center displacement in nominal grid mm, image axes |
| --- | --- | --- | --- |
| 60 | +1.83% | +0.96% | -2.46, -0.45 |
| 63 | +0.99% | +0.20% | -1.92, -0.14 |
| 66 | +0.62% | -0.38% | -1.43, +0.22 |
| 69 | -0.25% | -1.11% | -0.93, +0.58 |
| 72 | -0.88% | -1.63% | -0.46, +0.84 |
| 75 | -1.60% | -2.35% | +0.06, +1.17 |

Among sampled heights, 66 mm gives the smallest combined pitch mismatch, but neither axis matches exactly and the inferred displacement varies materially with assumed height. This is not a measured physical height or an approved robot correction. Outer-rim approximation, perspective, tilt, camera calibration and the unverified API/metal-deck height datum prevent a unique executable offset. No height value was written to the instrument.

Rechecked the exported labware: VisionLabwareHeight is 63, framed alignment uses a local mating point Z of -5.8, and labware 273 identifies a framed tip rack. These do not provide the complete transform from the physical deck through the pedestal to the nozzle. Hamilton identifies the proper Prep framed tip pedestal as part 6600553-01 (https://www.hamiltoncompany.com/other-robotics/6600553-01). A side view of the current physical support stack is needed to verify the operator's 75 mm reference against the mounted rack arrangement. The old photo depicts a different setup and is not sufficient evidence for the current holder.

Also captured the parked full-deck calibration overlay and camera parameters. The parameter endpoint exposes exposure/gain settings, not a camera-to-robot transform. No camera recalibration was performed. Final read-only checks: Idle, parked true, no tips attached.

Evidence: [six-height results](camera_height_comparison/results.json), [63 mm overlay](camera_height_comparison/overlay_63.png), [66 mm overlay](camera_height_comparison/overlay_66.png), [75 mm overlay](camera_height_comparison/overlay_75.png), [parked calibration overlay](camera_height_comparison/parked_calibration_pattern.jpg).

## Camera alignment after restored holder and restart, 25 October 2026 UTC

The operator restored the tips to the printed holder and reconfirmed 75 mm from metal deck to tip opening. After startup, the instrument was Connected, Idle, Not Initialized, door closed, enclosure present, no attached tips, and no pending errors. The unparked gantry obstructed the camera. Normal initialization through HamiltonPrep completed successfully (request f0b968b4266f43ca8115e08be7298cc4), leaving Initialized, Idle and parked. No pickup, offset change, or calibration routine was executed in this check.

Captured a clear full-deck image, vendor site-3 tip-grid overlays at API zHeight 75 and reference 63, and a matching plain site-3 crop at 75. The rack is visible at site 3. The API crop defines height relative to the bottom of the deck position; equivalence to the operator's metal-deck reference is not verified. The two height assumptions visibly change the grid comparison.

Exploratory offline outer-rim detection found 82 candidates; 76 fit a regular lattice within 3 pixels. At assumed API height 75, the fitted lattice center differs from overlay cell centers by approximately (+0.2,+7.2) image pixels. Observed column/row pitch is 56.13/55.61 pixels versus overlay 57.02/56.96, around 1.6%/2.4% smaller. The rack is approximately square to the overlay, but mismatch is not a pure translation. These estimates do not establish a nozzle correction: perspective, rim detection, height reference and holder tilt remain potential contributors. Image axes have not been mapped to robot motion axes. No executable correction or pickup success is inferred.

Evidence: [clear deck](parked_deck.jpg), [75 mm assumed-height overlay](site3_grid_assumed75.png), [63 mm reference overlay](site3_grid_reference63.png), [image analysis](tip_grid_image_analysis.json). Analysis code is read-only and does not issue robot commands.

## Repositioned insert trial, 25 October 2026 00:01 UTC workstation time

Following the preceding visual-observation test, the operator reported an offset approach from the left and sideways movement to the right. They clarified that the tip insert moved within the printed holder, resting on its inner recessed ledge; the outer holder itself was secure. This is operator-observed evidence of lateral contact, not a measured calibration offset. No deeper motion or software offset was applied. After the operator explicitly confirmed securing AND repositioning the insert, ran one authorized standard pickup diagnostic with unchanged OneChannel / labware 273 / site 3 / ejectToWaste true payload.

Fresh preflight passed door, enclosure, identity, initialization, Idle, no tips, and no active workflow checks. Both channels again reported did not detect the expected tip type in the rack. Selected Abort on this run's runtime error group. Aborted/finished events and a fresh Abort run completed trace confirmed termination. Final status: Idle, Initialized, no attached tips, pending-errors empty, parked false. No further movement was sent. Whether lateral contact persisted after repositioning awaits the operator's visual report.

Evidence: [run journal](core_pickup_20261025T000151Z.jsonl), [abort](repositioned_insert_abort.json), [final state](repositioned_insert_final.json).

## Visual-observation pickup, 24 October 2026 23:58 UTC workstation time

At the operator's request to watch alignment by eye, ran one diagnostic with unchanged geometry and the standard OneChannel / labware 273 / site 3 / ejectToWaste true payload. Fresh readiness checks passed, including door closed, enclosure present, Initialized, Idle, no attached tips, and no active workflow. The controller ran Tip_Pickup_Test_2_Channel. This attempt's runtime error group contained only **Rear Channel did not detect the expected tip type in the rack**. No front-channel error was included; this alone does not establish successful front pickup or single-channel selection behavior.

Selected Abort on the current runtime error group. Aborted/finished events and a fresh Abort run completed trace confirmed termination. Final status: Idle, Initialized, no attached tips, no pending errors, parked false. No offsets or calibration values were changed. Operator's visual findings are pending.

Evidence: [run journal](core_pickup_20261024T235818Z.jsonl), [abort](visual_observation_abort.json), [final status](visual_observation_final.json).

## Printed-holder retry, 24 October 2026 23:45 UTC workstation time

The operator reported that the printed holder was tight and explicitly requested another attempt. Sent exactly one standard pickup diagnostic after fresh readiness guards passed, with OneChannel, labware 273, site 3, and ejectToWaste true. No geometry or calibration values were changed. Hamilton again ran Tip_Pickup_Test_2_Channel and reported that both front and rear channels did not detect the expected tip type in the rack. This does not establish holder looseness as the cause or confirm that the API isolated one channel.

Added sensor-status sampling to the diagnostic monitor. Successful sampled readings showed both sleeve sensors false; one sensor read returned HTTP 400 during the attempt. Sampling cannot exclude brief transitions. The final has-tips reading was false. Selected Abort on this attempt's runtime error group, and a subsequent fresh trace confirmed Abort run completed. Final state: Idle, Initialized, no tips attached, pending-errors empty, parked false. No further motion was sent. The instrument clock differs from workstation time; the attempt is identified by its journal and error group.

Evidence: [retry journal](core_pickup_20261024T234533Z.jsonl), [abort response](printed_holder_retry_abort.json), [final status and completion trace](printed_holder_retry_final.json).

## Outcome on 24 October 2026

The Hamilton Microlab Prep successfully completed Database Backup after a restart followed by running backup before initialization or calibration. The new backup was **241,939,329 bytes**, approximately **242 MB**. Hamilton reported `Execution completed`, Database Backup status `Ok`, and global state `Idle`. Execution took approximately **14 seconds** on this successful attempt.

The previous prolonged backup attempt had been rejected because a common workflow was still pending. The application nevertheless remained in `MaintenanceAssayRunning`, with a spinning touchscreen. Waiting longer did not resolve that rejected attempt. The pending initialization/calibration work had to be cleared before trying maintenance alone.

**Operator update:** After the successful backup, the operator confirmed: "Initialization was a success." Initialization is therefore recorded as successful based on the operator's report.

**Subsequent API verification:** Initialization reports `Initialized`. Database Backup and Data Maintenance both report `Ok`, expiring 31 October 2026; Data Maintenance last execution is `2026-10-24T14:09:20.701Z` on the instrument clock. Self-calibration completed after acknowledgment of hidden Close Door and Complete prompts. Final checks showed `Execution completed`, global state `Idle`, instrument `Initialized`, and no pending errors. Pipetting and a complete Bioyond/Hamilton workflow remain unverified.

These notes concern the Hamilton instrument and its software. The separate [robot-arm observations](../hamilton/Observations.md) concern Bioyond travel and station approach.

## Instrument and connection

| Item | Observed value |
| --- | --- |
| Instrument | Hamilton Microlab Prep, two independent channels |
| Reference | `6600200-02` |
| Serial and instrument name | `PRPGD2427` |
| Internal PC | `192.168.100.101` |
| Controller board | `192.168.100.102` |
| Controlling PC name | `DESKTOP-9DPRVQ3` |
| Connected system after normal startup | `MLPrepTwoChannel_0` |
| Local workstation Ethernet address used | `192.168.100.15/24` |
| Core installer | `3.4.0.00084` |
| Server | `3.4.0.00125` |
| Client | `3.4.0.00127` |
| Device Controller | `3.4.0.00052` |
| Service and Repair Utility | `3.4.0.00018` |

Enclosure and individual channels were reported present. MPH8, HHS, HHC, and HEPAUV were reported absent. Instrument configuration reported a real instrument, not a simulated one.

The workstation reaches the internal PC over the Ethernet switch. The internal PC's software communicates with the instrument controller. Ethernet is the transport for the HTTP API; it is not an alternative to the API.

- API base: `http://192.168.100.101/NimbusLite/api/v1`
- Swagger UI: `http://192.168.100.101/NimbusLite/api-docs/index.html`
- OpenAPI specification: `http://192.168.100.101/NimbusLite/swagger/v1/swagger.json`
- Events: `ws://192.168.100.101/NimbusLite/instinctevents`
- Runtime errors: `ws://192.168.100.101/NimbusLite/instincterrors`

The root HTTP page is an IIS page, not the instrument interface. The controller board accepted a TCP connection on port 2000, but its raw command protocol was not established and no raw control commands were sent. An RDP connection file was prepared, but an authenticated remote desktop session was not established.

Requests used in this session worked without an explicit bearer token in this configuration. The vendor API documents authentication; do not assume another installation or every endpoint behaves identically.

## Attempts and observations

### Connection and browser errors

Initial connectivity was intermittent. HTTP requests sometimes succeeded and sometimes timed out; the internal PC's ARP entry was also observed as incomplete or unreachable during an outage. Connectivity recovered without a network configuration change by the assistant.

Swagger displayed `Failed to fetch`, listing CORS, network failure, and URL scheme as possible explanations. The requested initialization URL was correct. Requests outside the browser also timed out during outages, so a CORS-only diagnosis was not established. A successful TCP or HTTP connection did not imply that the instrument was initialized or ready to move.

### First initialization and maintenance attempt

After the operator confirmed the door was closed, Bioyond was clear, and the deck was ready, one initialization request was sent. It returned HTTP 200 and the global state changed to `Initializing`. Connection information continued to report `Not Initialized`. The operator observed no movement and a normal home screen. There were no pending API errors.

The operator identified overdue Database Backup and Data Maintenance and started maintenance through the touchscreen. The backup screen continued spinning. Touchscreen Cancel also spun. One API maintenance-abort request returned HTTP 200, but the state remained `MaintenanceAssayRunning` and no new backup appeared.

The operator powered off the instrument. Both previously reachable endpoints became unreachable, consistent with shutdown. The subsequent startup returned the instrument to `Idle`.

### Initialization after restart

A fresh check showed the correct instrument connected, services running, global state `Idle`, and no pending errors. Both data routines were still marked `Blocking`.

One initialization request was sent with event monitoring already connected. Planning and scheduling completed, but no execution-start event followed. Hamilton remained `Initializing / Not Initialized`, and the operator again reported no movement. A protocol-run query reported no protocol in progress.

### Calibration attempt

At the operator's request, one `POST /calibration/self-calibration` was sent while initialization was still unresolved. The HTTP request timed out, but server-side activity continued. It was not retried.

The calibration procedure selected `TiprackTestSystem`, emitted preparation events and a custom-dialog event, and the public global state returned to `Idle`. The touchscreen stayed on Home. Trace inspection identified the hidden dialog as **Close Door**, requiring an OK acknowledgment.

After the operator reconfirmed the door was fully closed, the recorded dialog ID was acknowledged once using `POST /calibration/close-view`. Hamilton explicitly marked that dialog handled and logged its closure with OK. Calibration planning and scheduling then completed, but execution and calibration completion were not observed. No new channel-calibration result was recorded.

The server log showed `CalibrationAssayRunning` followed by an underlying Idle event and a global Idle state before calibration had completed. Thus, public `Idle` alone was insufficient to establish that no prepared common workflow remained. A software state-handling issue is suspected; the precise cause of these failed attempts was not established. A later initialization succeeded, as reported below.

### Repeated backup and confirmed workflow conflict

The operator started Database Backup again. It remained on a spinner for an extended period, including a reported half hour and an additional waiting period. No new backup appeared.

Inspection of error history and the diagnostic archive tied the following error to that backup's start attempt:

> It is not possible to start a Maintenance and Verification Workflow if a Common Workflow is pending.

The error ID matched the dialog that the server automatically handled at the same start attempt. The application had already set `MaintenanceAssayRunning` and logged that backup was started, despite the rejection. The verification-status endpoint reported no active workflow, run, or service routine. These contradictory summaries explain why polling only the global state and pending-errors list was misleading.

The preceding calibration remained scheduled. Calibration-abort and maintenance-abort requests each returned HTTP 200, but neither cleared the reported maintenance state. A factory reset was discussed but **not verified or performed by the assistant**. The operator subsequently restarted the instrument; existing backup history remained present.

The assistant should have inspected error history and execution traces immediately after backup start, rather than recommending more waiting based on a spinner and an empty pending-errors list. Starting calibration before the unresolved initialization was cleared also made the workflow state harder to interpret.

### Successful backup after clean startup

Before backup, two read-only checks established:

- Global state `Idle` and no protocol in progress.
- No verification workflow, verification run, or service routine in progress.
- No pending errors or maintenance errors.
- No new scheduler activity since restart.
- Correct system `MLPrepTwoChannel_0` connected to `PRPGD2427`.
- Required services running.

Startup had logged a handled failure loading the previous `TiprackTestSystem` template. The current-system query nevertheless showed the normal two-channel configuration active and connected. This was recorded rather than treating the entire error history as empty.

The operator started **Database Backup as the first workflow after restart**. The assistant sent only read-only checks during this attempt. This time there was direct evidence of execution:

| Evidence | Observed value |
| --- | --- |
| Scheduler execution started | `2026-10-24T14:04:55.9180389Z` in instrument trace |
| Backup Database activity started | `2026-10-24T14:04:58.6316302Z` in instrument trace |
| New file | `Backup_2026-10-24 07-04-59Z` |
| Initial observed file size | `94,136,982` bytes |
| Final observed file size | `241,939,329` bytes |
| Execution completed | `2026-10-24T14:05:09.1776282Z` in instrument trace |
| Database Backup status | `Ok`, expires `10/31/2026` |
| Final global state | `Idle` |

Elapsed execution was about 13.3 seconds, rounded to about 14 seconds in the session. The backup activity itself took about 10.4 seconds. This is one measured successful attempt, not a vendor guarantee for future backup durations. The operator confirmed that backup worked.

**Clock caution:** workstation journal times and instrument timestamps differed by roughly 50 minutes in this session. Keep each clock's timestamps separate; do not subtract an instrument time from a workstation time to calculate a duration. The elapsed times above use the same instrument clock. Preserve backup filenames exactly as returned, including their `Z` suffix.

### Initialization succeeded after backup recovery

Following the successful backup and documentation of the recovery, the operator reported that initialization succeeded. This is a subsequent successful attempt, not a reinterpretation of the earlier stalled requests. Its exact command source, timing, and intervening Data Maintenance actions were not specified. Calibration completion and pipetting performance remain unverified.

### Later self calibration and hidden prompt recovery

The operator encountered `Cannot perform the requested operation because the affected document is currently used in execution!` during self-calibration. A read-only check after the operator cleared commands still showed `CalibrationAssayRunning`, active system `TiprackTestSystem`, and a recent Close Door prompt. The protocol-run flag alone reported no run in progress, again showing that it cannot establish absence of calibration work. Two document-in-use errors remained unhandled in error history, while the pending-errors endpoint returned an empty list.

The touchscreen showed only Home. A fresh diagnostic export identified the current dialog as `3e554d9cd93e41158de85a2012e37440`; this was a different dialog from the first calibration attempt. After the operator confirmed the door was fully closed, the assistant acknowledged that dialog once through `/calibration/close-view` at workstation time `2026-10-24T15:23:14Z`.

Hamilton confirmed the dialog handled, then emitted `Scheduled`, `Starting`, and `Running` events. The Calibration activity started at workstation time `15:23:18Z` (instrument trace `14:33:03Z`). This time execution actually began. The emitted instruction was to wait for calibration and not power off.

The operator subsequently reported successful calibration. The trace confirmed the Calibration activity completed at instrument time `14:35:26.960Z`, approximately 143 seconds after activity start. A final hidden **Complete** dialog still required OK, so the overall workflow remained open. The assistant identified its current ID, `fb4a7e1f268b412aa6831b21ee54d54b`, from a fresh diagnostic export and acknowledged it once at workstation time `15:27:55Z`.

After termination finished, the trace recorded `Execution completed` at instrument time `14:37:49.161Z`. At workstation time `15:28:10Z`, the API reported `Idle`, `Initialized`, and no pending errors. This distinguishes completed calibration activity from completion of the entire workflow and release of its resources.

The channel-results endpoint still returned only the historical July/August failures, with no new row for this run. Success here is supported by the operator report and execution traces; persistence of a new channel-results record was not demonstrated, and no result was manually inserted. The old motor-stall records must not be attributed to this successful attempt.

Evidence: [read-only commands-cleared check](commands_cleared_check_20261024T152050Z.json), [hidden-dialog diagnostic archive](diagnostics_hidden_calibration.zip), and [acknowledgment and execution journal](calibration_hidden_prompt_20261024T152313Z.jsonl).

Completion evidence: [completed activity and pending final prompt](calibration_completion_20261024T152717Z.json), [completion diagnostic archive](diagnostics_calibration_complete.zip), and [final acknowledgment and verified idle state](calibration_final_ack_20261024.json).

## Practical procedure established by this session

1. Following a recovery restart, check readiness, connection, all exposed workflow states, pending errors, recent error history, and recent scheduler traces before launching a workflow.
2. Run Database Backup alone before starting initialization or calibration when recovering from this specific conflict. This order succeeded here; it is not a claim that Hamilton universally requires backup before initialization.
3. Immediately check for new error-history entries, even if marked handled. Look for `Execution started` and the backup activity starting, then a new file and its growth. A spinner or HTTP 200 is not proof of execution.
4. Confirm completion through execution-complete traces, Database Backup status `Ok`, and return to `Idle`.
5. Run Data Maintenance next and verify its completion separately. Only then recheck readiness for initialization. Do not start multiple workflows concurrently.
6. If a workflow is rejected, diagnose and clear the pending workflow before retrying. Do not assume a successful abort response actually cleared it. A timeout leaves the outcome uncertain: inspect state and events rather than resending a motion or start command.
7. For API-driven interactive procedures, subscribe to events and errors before starting. The event `data` and nested payloads may be JSON-encoded strings. Identify the actual prompt, preserve its dialog ID, and acknowledge only after its requirements are satisfied. The touchscreen may not display an API-created prompt.

Use multiple signals because the global state was misleading in both directions: maintenance appeared running after rejection, while calibration appeared idle with prepared work pending. There is no demonstrated single query in this session that proves every internal queue is empty.

The API exposes `POST /maintenance/initialize`, described as creating initial maintenance values for a fresh installation or updates. It was not used as a substitute for performing maintenance. No completion records, calibration results, or maintenance dates were fabricated to bypass the block.

## Other findings and unresolved issues

- Earlier calibration history contained failures reporting `Front Channel channel motor stalled`, dated July and August. Those historical failures do not establish a current motor fault or explain this backup rejection.
- Startup history included active-system/configuration load failures. Current connection checks recovered to the correct system after normal startup; the cause of those startup errors was not resolved.
- Diagnostics reported approximately 519 MB database size and 184 GB free disk space, with storage checks passing. Database size or lack of disk space was not established as the cause of the prolonged backup screen.
- Server logs recorded maintenance-importance changes through the local application. Data Maintenance and Database Backup remained blocking. A verified API override for these routines was not implemented, and generic camera-warning override settings are unrelated.
- The existing Lacry/Hamilton adapter and bridge had not been integrated with this verified Prep API. Instrument connectivity and backup success do not mean an end-to-end laboratory roundtrip is operational.
- Factory-reset scope, calibration/configuration preservation, and a restore procedure were not verified. No factory-reset recovery was required for the successful backup.

## Evidence and references

Local evidence is in this directory. Some status files are snapshots that may later be overwritten; timestamped journals preserve individual attempts.

- [Downloaded OpenAPI specification](prep_openapi.json)
- [Read-only status script](check_status.py)
- [First initialization journal](initialize_20261024T121326126552Z.jsonl)
- [Initialization after restart](initialize_after_restart_20261024T125853Z.jsonl)
- [Calibration request and events](calibration_attempt_20261024T130526Z.jsonl)
- [Close Door acknowledgment and events](calibration_close_door_20261024T130807Z.jsonl)
- [Diagnostic archive after calibration](diagnostics_20261024.zip)
- [Diagnostic archive for the rejected backup](diagnostics_backup_stalled.zip), including `ServerLogs/NLServer_20261024.log` and `Errors.json`.
- [Recovery abort journal](recover_pending_workflow_20261024T144627Z.jsonl)
- [Clean startup preflight](backup_preflight_20261024T145359Z.json)
- [Second preflight](backup_double_check_20261024T145435Z.json)
- [Successful backup start and initial file growth](backup_started_check_20261024T145519Z.json)

The final completion values above were read directly from the API in the session after that last snapshot and confirmed by the operator; the start snapshot alone does not contain completion evidence.

Vendor references used during troubleshooting:

- [Access the local Swagger interface](https://developer.hamiltoncompany.com/pages/prep_guide_access_swagger)
- [Prep API reference](https://developer.hamiltoncompany.com/products/prep/api/openapi)
- [Real-time events](https://developer.hamiltoncompany.com/pages/prep_guide_connect_realtime_events)
- [Run maintenance](https://developer.hamiltoncompany.com/pages/prep_recipe_run_maintenance)
- [Prep troubleshooting and channel calibration](https://www.hamiltoncompany.com/knowledge-base/faq/my-ml-prep-isnt-working)
- [Database backup export and restore](https://www.hamiltoncompany.com/knowledge-base/faq/does-the-prep-support-21-cfr-part-11)

For the next session, begin with fresh state checks. Initialization, both data maintenance routines, and self-calibration have completed; the final calibration acknowledgment returned the instrument to `Idle / Initialized`. A complete pipetting workflow and persistence of a new channel-results record still require verification.

## 2026-10-24: dry pickup diagnostic failed; aborted to Idle

This later result supersedes the initialized state above. The operator identified Hamilton 235938 300 uL CO-RE tips in a Prep tip pedestal and confirmed door closed, hands clear, and Bioyond arm clear. One diagnostic start was sent at workstation 17:40:02 UTC, using catalog labware ID 273 (235903, 300 uL framed conductive filtered), deck position 3, `channelSelection: OneChannel`, and `ejectToWaste: true`. No custom geometry or calibration changes were made. A preceding websocket connection attempt failed before any start request; local websocket proxy handling was corrected before the single actual start.

The API returned HTTP 200, but execution failed in `Pick Up Tips`. The fuller error history records **Front Channel channel motor stalled** and **A coordinated move was stopped**, followed by both channels reporting aborted actions. These are new errors from this attempt, not the older calibration history. Their underlying mechanical cause is not established. Despite the OneChannel request, the execution activity was named `Tip_Pickup_Test_2_Channel` and both channels appeared in errors; actual single-channel operation is not verified.

Selected Abort on the observed runtime error group at workstation 17:40:39 UTC. Events and traces confirmed abort completed and return to Idle. Final checks: connected true, **Not Initialized**, has-tips false, pending-errors endpoint empty. Some underlying history entries remain marked unhandled. The pending-errors endpoint also returned empty while the runtime error was active, so it must not be used alone to establish readiness. No retry was sent; pickup and ejection success were not established. Inspect the physical pickup situation and diagnose the stall before another movement attempt.

Evidence: [complete request and event journal](core_pickup_20261024T174002Z.jsonl), [abort response](core_pickup_abort_response.json), and [final connection state and detailed error history](core_pickup_final_details.json). Instrument log timestamps differ from workstation timestamps; use each clock consistently.

## Lacry Hamilton integration and automatic door requirement

### Printed holder trial, 2026-10-24 23:43 UTC

The operator measured 75 mm from metal deck to the top opening of a seated tip and initially described the new printed holder as sitting on the pedestal. They clarified that it reproduces the normal Hamilton holder configuration using the same print. The exported labware's VisionLabwareHeight is 63 mm, but this field alone is not a verified mechanical pickup height or proof of a 12 mm pickup mismatch. No Z offset, labware definition or calibration was changed.

With the operator's renewed trial authorization, preflight passed Idle, Initialized, door closed, enclosure present, no tips and no active workflow checks. Sent one standard request at workstation 23:43:54 UTC: OneChannel, labware 273, site 3, ejectToWaste true. Both channels again reported **did not detect the expected tip type in the rack**. Selected Abort once; aborted/finished events and Idle confirmed termination. Final state: Initialized, no attached tips, no pending errors, parked false. The new holder did not resolve this attempt's fault; exact cause remains unverified.

Evidence: [measurements](printed_holder_measurements.json), [journal](core_pickup_20261024T234353Z.jsonl), [abort](printed_holder_abort.json), [final state](printed_holder_final.json).

### Requested pickup after coupling photos, 2026-10-24 23:35 UTC

The operator supplied IMG_6332.jpeg and IMG_6333.jpeg showing both red O-rings and an exposed coupling under a raised eject sleeve. No obvious major fracture was visible, but mechanism function and ring condition were not established. The operator canceled a proposed self-calibration before any write was sent; only its readiness check ran. An earlier separate request to home the heads completed successfully and confirmed parked true.

At the operator's renewed pickup request, preflight found Idle, Initialized, parked, door closed, enclosure present, both sleeve sensors false, no attached tips, and no active workflows. Sent exactly one standard dry pickup request at workstation 23:35:54 UTC: OneChannel, labware 273, site 3, ejectToWaste true. The diagnostic again ran Tip_Pickup_Test_2_Channel and both channels reported **did not detect the expected tip type in the rack**. Selected Abort once on the current error group; aborted and finished events confirmed termination, followed by Idle. Final checks: Initialized, no tips, no pending errors, parked false. No geometry changes or automatic pickup retries occurred.

Evidence: [journal](core_pickup_20261024T233553Z.jsonl), [abort](one_channel_2335_abort.json), [final state](one_channel_2335_final.json).

### Requested OneChannel repeat at site 3, 2026-10-24 22:46 UTC

After the operator reported selecting site 4 on the touchscreen, a read-only camera check showed the rack still at the position previously identified as site 3 and the well plate beside it. The newer touchscreen-associated logs contained no-tip-present errors for both channels, distinct from the API expected-tip-type errors. This does not establish the cause of the earlier API failures, which already used site 3.

The operator requested another OneChannel test while considering holder security. Explained before starting that this setting had not isolated one head. Changed the saved diagnostic script back to OneChannel and sent one start at workstation 22:46:52 UTC, retaining labware 273, site 3 and ejectToWaste true. Preflight passed Idle, Initialized, door closed, enclosure present, no tips and no active workflows; no separate reinitialization was sent this time. The diagnostic again ran Tip_Pickup_Test_2_Channel, and both channels reported **did not detect the expected tip type in the rack**. Selected Abort on this run's error group; aborted/finished and Idle confirmed termination. Final status: Initialized, Idle, no tips, no pending errors, parked false. The test did not establish single-channel isolation or whether rack security causes the failure.

Evidence: [journal](core_pickup_20261024T224651Z.jsonl), [abort](one_channel_2246_abort.json), [final state](one_channel_2246_final.json), [touchscreen-associated error check](touchscreen_pickup_check.json), [deck image](deck_site_check.jpg).

### Explicit TwoChannel comparison, 2026-10-24 22:29 UTC

The operator explicitly requested changing channelSelection to TwoChannel as an experiment. Changed only that field in run_core_pickup_test.py; labware 273, site 3, ejectToWaste true and preflight guards stayed the same. Reinitialization succeeded, followed by one diagnostic start at workstation 22:29:49 UTC. The activity again was Tip_Pickup_Test_2_Channel, and both front and rear channels reported **did not detect the expected tip type in the rack**. Changing OneChannel to TwoChannel did not resolve the pickup failure; this result does not prove whether channelSelection is honored internally.

Selected Abort on this run's error group. An initial local journal lookup used the wrong filename second and failed before sending a request; the actual journal is stamped 22:29:48. The subsequent Abort request returned HTTP 200. The monitor ended before abort completion, so a fresh trace read independently confirmed **Abort run completed**. Final state: Idle, Initialized, no tips attached, no pending errors, parked false. No additional pickup or geometry change was sent. The saved diagnostic script now explicitly uses TwoChannel.

Evidence: [TwoChannel run journal](core_pickup_20261024T222948Z.jsonl), [abort response](two_channel_abort.json), [final status and abort-complete trace](two_channel_final.json).

### Another requested reset and dry test, 2026-10-24 22:24 UTC

At the operator's explicit request, reinitialized successfully to Idle, Initialized, parked true, then sent one dry pickup diagnostic with the unchanged standard payload after passing the preflight checks. Both channels again reported **did not detect the expected tip type in the rack**. Selected Abort on this attempt's runtime error group; aborted/finished events and Idle confirmed termination. Final status remained Initialized, no tips attached, no pending errors, parked false. No automatic retry or parameter override was used. Reinitialization alone has not resolved this recurring error; verify the actual tip/rack configuration before further pickup attempts.

Evidence: [run journal](core_pickup_20261024T222401Z.jsonl), [abort](dry_retry_2224_abort.json), [final status](dry_retry_2224_final.json).

### Reset and another authorized dry test, 2026-10-24 22:21 UTC

The operator requested reset and retry after securing the previously loose plate. Reinitialization through the existing adapter completed with Idle, Initialized, and parked true. Fresh dry-test preflight passed door/enclosure, initialization, no attached tips, and no active workflow checks. Exactly one diagnostic start was sent at workstation 22:21:11 UTC with the same standard payload (OneChannel, labware 273, site 3, ejectToWaste true).

Both channels again reported **did not detect the expected tip type in the rack**. Selected Abort on the current error group; Hamilton emitted aborted and finished, followed by Idle. No further pickup was attempted. Final checks: Initialized, Idle, no tips, no pending errors, parked false. Securing the plate and reinitializing did not resolve the detection failure; the underlying cause is still unverified.

Evidence: [run journal](core_pickup_20261024T222111Z.jsonl), [abort](dry_retry_2221_abort.json), [final status](dry_retry_2221_final.json).

### Later dry pickup retry, 2026-10-24 22:17 UTC

The operator confirmed replacement with a firm holder, a physically closed door, and an unmodified interlock with no magnet override. Fresh preflight found Initialized, Idle, parked, no tips, enclosure present, door closed, no active protocol or verification workflow, and no pending errors. The deck camera showed the tip rack at site 3 and a plate beside it. The original diagnostic script was strengthened to check door, enclosure, initialization, instrument identity, and workflow state before sending a start.

Exactly one `PUT diagnostics/instrument/tip-pickup` was sent at workstation 22:17:05 UTC with the existing payload: OneChannel, labware 273, site 3, ejectToWaste true. Hamilton ran an activity named Tip_Pickup_Test_2_Channel. Both channels reported **did not detect the expected tip type in the rack**. No successful pickup or ejection was established. The cause remains unresolved; the error does not establish whether the tip definition, rack seating/height, or another pickup condition is responsible.

Selected Abort on the newly received runtime error group, without retrying. Hamilton emitted aborted and finished, and traces confirmed Abort run completed. Final status: Idle, Initialized, has-tips false, parked false, pending errors empty. No subsequent motion was sent. The heads must not be assumed parked for robot access.

Evidence: [retry journal](core_pickup_20261024T221705Z.jsonl), [abort response](dry_retry_abort.json), [final status](dry_retry_final.json), and [preflight camera](dry_retry_camera_preview.jpg).

The operator reported a loose tip holder and planned to replace it. No repeat pickup was attempted during software integration. Lacry now uses a direct Prep adapter with a Hamilton panel, deck snapshots, initialization/self-calibration plans, error and prompt visibility, durable run journals, and native agent tools. Its existing same-plate Hamilton/Squid round-trip planner accepts an optional one-time Hamilton calibration and the full requested repetition count under one confirmation. Offline verification passed 86 relevant unit tests plus fixture-only Edge checks at desktop and mobile widths. The live console was reloaded while idle, the arm connection was restored without motion, and the arm pose was verified unchanged. The new adapter's live writes have not been commissioned.

Read-only checks through the reloaded UI confirmed PRPGD2427 connected, Idle, Not Initialized and not parked. No commissioned liquid-handling recipe is configured, and the automatic loaded handoff still requires its existing acceptance evidence. See [integration details](../../HAMILTON_INTEGRATION.md) and [live UI check](lacry_hamilton_live_check.json).

The operator explicitly requires automatic door opening for arm access and confirmed that the current door is opened by hand, with no actuator installed. The installed API documents only door-state GET and event-subscription POST on `service-software-api/doorstate`; no door open/close actuator command was found. The GET returned an empty body, and the newer `is-door-closed` endpoint returned 404. No interlock or enclosure setting was modified. A supported motorized opener and verified open/closed feedback, or another Hamilton-approved robot access arrangement, remain prerequisites for unattended round trips. [Read-only capability check](door_capability_check.json).
