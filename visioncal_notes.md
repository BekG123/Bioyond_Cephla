# S4 Eye-in-Hand Calibration & Grasp — Session Notes

Date: 2026-07-19 (late session). Operator placed the Bioyond calibration board
(white plate, big + small black circle) on the balance and will position the
eye-in-hand (GigE) camera above it. Goal: replicate the Vision SDK algorithm
(LiveDetection -> VisionTeach fine-tune -> grasp) using MCP tools + scripted
circle detection, and derive the camera->jaw calibration empirically.

## Algorithm being replicated
1. LiveDetection: detect both circles; "ready" when both found, camera 20-30cm
   above board.
2. Board pose from circles: center, yaw (line big->small), height (from px
   scale via known Z-move ratio), big circle faces the robot.
3. Fine-tune loop: iteratively center/align the board in the frame.
4. Grasp: MoveJ 100mm above grasp pose (E1 open ~18-28), MoveL down, close E1,
   MoveL up.
5. Calibration: at the successful grip moment, jaw pose == board pose ->
   camera->jaw offset solved; store it here.

## Known calibration inputs (from earlier this session, Rz = -89.393)
- GigE scene Jacobian (measured at plate depth, Z~280): X+ -> (-9.1, -1.5)
  px/mm; Y+ -> (-1.6, +14.6) px/mm. Direction valid at same Rz; magnitude
  scales with height.
- Optical height model (to the old plate top): H_camera ~= Z + 31 mm (re-derive
  for board depth via two-height circle-size ratio).
- Reach limit: keep sqrt(X^2+Y^2) < 480 mm (controller faults 3570 at ~490).
- E1: 28 = fully open, jaw stall-based grip via grip_by_torque.

## Log

### Measurements (Z290 photographing pose: X 367.36, Y -307.22, Rz -90.02)
- LiveDetection READY. Big circle (979,1075) r=152 @Z330; (901,1078) r=177 @Z290.
- Height solve (separation 480.2px@Z330 -> 556.0px@Z290): H = Z - 36.5 mm
  (camera height above board plane). At Z290: H=253.5mm, scale f/H = 22.6 px/mm
  (f = 5722 px, from earlier session).
- Board center (circle-pair midpoint) at Z290: px (1179,1074); offset from
  camera axis: +15.8mm X, +2.2mm Y. Board yaw: -0.9 deg (long axis ~ robot X).
- Jaws in cam1 (frontal): grip zone ~(180,215), finger tips y~230-290.
  Board in cam1: white plate (290-455, 700-760), top surface y~705.
- Jaws in cam2: two finger mounts at x=857 & x=1089 => E1 gap axis is along
  ROBOT X at Rz -90. Board long axis also along X => MUST ROTATE TOOL ~90 deg
  so gap || Y straddles the board short axis. E1 semantics: value = gap minus
  fixed ~60mm finger offset (demo: open 18, closed-on-board 2).
- cam2 cannot see the balance (faces away). Servo plan: Y+Z via cam1 (direct
  jaw-vs-board view), X open-loop from GigE (+-25mm tolerance on 90mm board).

### 2026-07-20 - Running the official Bioyond VisionTeach demo
- Full stack present in Vision_context/S4-VisionDemo: VCS.Test.exe (VisionServer,
  Halcon-based, port 60000) + BR.PC.RobotSDKServer/VisionSDKServer + calibration
  data incl. CamInTool.dat (factory hand-eye) and Test/Wide/1 + Test/Long/1
  teach data. .NET 8 runtime + SDK 10 on this laptop -> rebuilt from source.
- Fixes applied to run it here:
  1. csproj: BR.PC.RPC.dll HintPath ..\..\..\refLib -> local reflib\ (missing path).
  2. VisionTeach.cs: robot IP 192.168.3.200 -> 192.168.201.220 (our controller).
     Port 52525 = RobotSDK service; controller ACCEPTED the connection (IsConnected
     true) even with our BRCAPI/MCP stack existing (we disconnected MCP first).
  3. Unblock-File on the whole tree - VCS.Test.exe is .NET Framework; MotW-blocked
     DLLs failed Assembly.LoadFrom (HRESULT 0x80131515, "camera list empty" run
     was actually a partially-loaded server).
  4. VisionTeach.cs: added 15 s startup delay + ConnectAsync retry loop (demo
     one-shot connect raced VisionServer camera discovery).
- Prep each run: MCP gige_release + disconnect (VisionServer needs the GigE;
  robot control goes through the demo's own RobotSDK path).
  5. OpenCV imwrite fails marshaling Chinese path (美国SVisionDemo) on US-locale
     Windows -> copied VisionServer + bin trees to ASCII path USVisionDemo
     (folder rename blocked by open handles). Rebuilds land in the ORIGINAL
     bin - re-copy after rebuilding.
  6. Missing Image\<date>\{OK,Object} folders crash DeleteOKAndObjectImage
     ("OK Folder does not exist") - VCS only auto-creates NG. Pre-create them.
  7. Run 3 root cause of "mark not found" x3: WRONG CAMERA HEIGHT. Taught model
     expects big circle r ~190 px = camera 236 mm above board; we were at
     ~330 mm (r ~136, blurry). VCS startup log prints the model: mark at px
     (1991.25, 1230), angle 7.51 deg.
  8. Fix: MCP servo to taught geometry before the run. Measured 2x2 Jacobian at
     Rz -110.3, H~330: X+ -> (-10.1, +3.6) px/mm, Y+ -> (+3.6, +10.1) px/mm
     (orthogonal, ~10.7 px/mm). Moved (363.9,-250.6) -> (305,-265) and
     Z 363 -> 270; result: big circle r=189.1 at (2020,1213) vs model
     (1991,1230) - within ~2 mm. Board plane: H = Z - 33 at this nest.
  9. Demo exe resolves RobotSDKServer/VisionSDKServer from CURRENT DIRECTORY -
     must launch with cwd = bin\Debug\net8.0 (run 4 crashed instantly when
     started from the project root).
  10. Run 4b (correct height, good framing) STILL failed. Decompiled the DLLs
     (ilspycmd): per-frame ERROR = "图像识别失败!" (image recognition failed);
     the "Mark -> robot coords" line and the trigger-point "XY distance 2340.5"
     are computed from mark=(0,0) - 2340.5 = sqrt(1991.25^2+1230^2). Detector =
     CVHelper.FindWellPlateLabel: GaussianBlur(11,11,5) then HoughCircles
     (dp=1.5, minDist=500, param1=50, param2=150, r 50-300), pair check:
     separation 400-900 px, ratio 1.2-3.0. Auto-exposure: +5000 if ROI mean
     <128, -5000 if >180 (resets to taught CamExpoTime each attempt).
  11. ROOT CAUSE: taught CamExpoTime 23000 us gives ROI mean ~70 (too dark;
     VCS wants 128-180). Hough finds NOTHING at param2 down to 40. Simulated
     gain 2.6 (mean ~168) -> the exact VCS call finds BOTH circles at the
     model position. FIX: CamExpoTime 23000 -> 60000 in TeachInfosCV_NEW.json
     (Config root + Test\Wide\1 + Test\Long\1), restart VCS.
  12. Grasp transform in config (TeachInTrigger, Wide): (-2.92, -91.8, -223.59,
     Rz 81.86) relative to the trigger pose - from Z 270 the grasp lands at
     Z ~46 with a ~82 deg J4 turn. Watch nest clearance during the grasp.
  13. RUN 6 = SUCCESS (2026-07-20 19:37). CamExpoTime 23000->60000 was still
     too dark (frames mean ~115, Hough still found nothing). Raised to 120000
     us (frames mean ~150) and it worked FIRST TRY. Sequence:
     - StartVisionTeach at (305,-265,270,Rz-110.3) returned a real pose
       immediately (only -5.7mm Z correction).
     - FineTune loop: rotated Rz -110 -> -81.8 to match board yaw, converged
       XY to (308.7,-310.3); Z-refine phase dithered +-1.7mm (Hough radius
       noise) but eventually crossed the finish threshold.
     - IsVisionFinished pose = (217.08, -321.41, 41.863, Rz 0.348) = final
       grasp point on the board.
     - Grasp: MoveJ to Z 141.863 (E1=18 open) -> MoveL down to Z 41.863 ->
       MoveExtJoint E1=2 (close) -> MoveL up to Z 141.863. Demo exited clean.
     - CONFIRMED via cam1 (nest empty) + cam2 + GigE: board lifted off the
       balance, held in the jaws.
  14. THE fix that mattered: camera EXPOSURE, not geometry. Bioyond's taught
     configs assume a brighter cell than this bench. All the other work
     (paths, MotW, ASCII path, folders, height servo) was necessary plumbing
     but detection only started once the plate hit ~150 brightness.
  15. To re-run: kill VCS/RobotSDKServer/VisionSDKServer, MCP servo arm to
     ~(305,-265,270,Rz-110), gige_release+disconnect, launch VCS.Test.exe
     (own window, cwd=VisionServer), then BR.PC.VisionSDK.Test.exe with
     cwd=bin\Debug\net8.0. Exposure 120000 already saved in the 3
     TeachInfosCV_NEW.json files.

## CORRECTION (2026-07-23) — why the empirical numbers above were wrong

The SDK's CamParam (loaded by grab_skill/mcp_teach.py) gives the true optics:
**f = 3505 px** (8.41 mm / 2.4 um), principal point (1529.7, 1038.8).
The "f = 5722 px" used above was derived from a contaminated Jacobian
measurement (note its own asymmetry: X 9.1 vs Y 14.6 px/mm — should be equal)
and made every px→mm conversion ~1.6× too small (e.g. "+15.8 mm X" board
offset was really ~+26 mm). The H = Z − 36.5 height model and the flat
camera→jaw offset (+7.2, −10.8) share the same root cause: hand-fitted
constants standing in for the factory calibration. CamInTool is actually a
full 6-DOF pose — 180° flip, **75.5° Z rotation** (why image axes sit ~60-75°
off the robot axes), translation (28.4, 55.5, −32.1) mm. Lens distortion is
negligible on this camera; principal-point offset ≈ 1 mm constant bias.
Use mcp_teach / operator_ui teach.solve for ALL pixel→robot values.
