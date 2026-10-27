# Researcher hand-guiding

Open **Researcher → Teach → Hand-guiding with DragGo**. Connect the robot,
support the arm, confirm the preparation checkbox, and select **Start
hand-guiding**. Wait for the controller-confirmed active message. Capture Home,
guide to Hamilton, hold still, and capture Hamilton. **End hand-guiding**
disables the servos before switching DragGo off. Support the arm during exit.
The page never releases the Z brake. Do not force a resisting joint.

Bioyond Works is not needed for this workflow and should stay disconnected.
Closing the browser does not turn DragGo off. A lost connection means state is
unknown, not that the arm stopped. Physical E-stop remains the emergency stop.
Captures are discrete positions; continuous imitation recording and replay
are still pending.

## Implementation and limits

### Claw opening

Further inspection on October 16: in the installed `BR.PC.BYSDK.dll`,
`RobotSDK.OpenGripperAsync` throws `NotImplementedException`;
`CloseGripperAsync` returns false in torque mode and throws otherwise.
The names in the SDK documentation do not establish working support.
`JogExtJointAsync` uses Manual mode, enable, native MotionGo, an external-axis
step, and MotionStop. Compatibility with this firmware and active DragGo remains
unverified. No new jog, gripper or mode-changing command was issued during this
inspection. Current controls still use the Auto/Lua path below.

Researcher Teach includes **Open a little (+0.2 mm)**, **Open claw**, and
**Stop opening**. These now call `RobotService.move_gripper`, the same Lua
service as Developer Open, at speed 5. Open targets the configured maximum
E1 (28 mm); Open a little adds 0.2 mm to fresh feedback.

If Auto is not ready, the UI requires an empty-gripper confirmation because
Lua startup can close the jaws. The shared preparation ends DragGo, prepares
Auto, and starts the program only if needed. It reads E1 after preparation,
checks measured arm stability, and verifies measured opening after the command.
Auto remains active afterward; select **Start hand-guiding** to guide again.
Stop prevents subsequent commands but does not interrupt a claw command already
sent. Rejection or unconfirmed arrival stops without automatic retry.

October 16 diagnosis: native external-axis commands 242 and 202 were rejected
in DragGo with `response=0`. These are command IDs, not collision codes.
The unused native opening method was removed in favor of the Developer path.
This firmware also reports `isMoving=true` in stationary DragGo, so the
Researcher control checks measured TCP and J1-J4 stability instead.
Offline tests cover preparation, post-startup E1, mode changes, rejected
commands, measured arrival, and Stop. Live opening remains operator-verified.

- `draggo.py` uses the controller's binary TCP interface on port 20202 alongside
  the existing pose/status connection on 56788. Python standard library only;
  no Works UI, DLL deployment, .NET runtime, or new Python package is needed.
- Restricted to the observed S4 `BRC-full` firmware `1.8.2504101654`, with the
  740-byte, Pack=4 motion-status structure. Other firmware fails closed until
  its protocol is verified. The native DragGo field is at byte 736.
- Command provenance: installed `C:\Bioyond\RobStudio\BR.PC.BYSDK.dll`,
  `BR.PC.LiquidStudio.Driver.Liquid.Control_MotionSetDragGo`,
  `Control_SetManualEnable`, `Control_ChangeMode`, `Control_SetAutoEnable`,
  and `CmdType`. Vendor Works Software Manual §5.4 describes the same
  disable → Manual → DragGo → enable sequence. Command IDs: motion info 10,
  system DI write 58 and DragGo 137. Auto disable uses the existing shared
  `remoteDisable` API; native command 136 is rejected by this firmware.
  No Lua/gripper/start/reset
  commands are sent.
- This older controller returns sequence zero and does not implement the
  newer SDK's client-registration query. Each request uses a fresh socket,
  one reply, a bounded timeout, and strict header/layout validation. There is
  no reconnect/retry of a mode-changing command and no client takeover.
  App-level ownership does not prevent another external application from
  independently controlling the robot; keep those clients disconnected.
- Start requires no active console sequence, no movement,
  no controller alert, and explicit operator preparation. Every transition
  is checked using fresh controller status. A supported-arm Start stops an idle
  running/paused controller program and verifies it is stopped before changing
  mode or enabling DragGo. A timeout or rejected stop prevents activation.
  End leaves the servos disabled;
  it does not restore Auto, return Home, or start playback.
- The shared dispatch/motion locks exclude conflicting console commands.
  Disable/Stop remain available and cancel activation. A local latch at
  `demonstrations/draggo-active.json` survives process restarts and keeps
  other commands blocked until End is verified. A transition failure attempts
  disable once and retains the latch; it never reports success from an ACK alone.

## Validation (2026-10-16)

Manual Descend/Grip capture now reads passive native motion status for E1.
The legacy JSON `getJointInfo` response has no external axes on this controller.
SDK `MotionGetInfo_resp` places `extJoint` at byte 336 and `extJointType` at
368; `RobotSDK.GetCurExtJointAsync` converts type 1 from metres to millimetres,
and rotary axes from radians to degrees. Captures require linear E1 and two
settled readings; no Lua report job or motion command is issued. Saved records
include the feedback source and units. Missing feedback leaves the draft intact
and displays a specific error beside the Record button.

Initial read-only hardware query confirmed firmware, Auto mode, disabled
servos, and DragGo off. Subsequent operator requests logged successful
Researcher start/exit, but exposed a parser bug: native motion state 6
(DragGo) was rejected. The parser now accepts the complete vendor state enum
(0–8), verified against live Manual/enabled/DragGo-on status. Disable now
skips a redundant command when fresh status already confirms disabled,
matching the vendor SDK. An already-off exit also skips the DragGo toggle.
These fixes have regression tests; full physical hand-guiding usability
and corrected exit still need operator validation.

Offline tests cover wire parsing, firmware rejection, activation/exit,
timeouts, interrupted activation, ownership and browser station capture.

At 09:01–09:02 PDT on October 16, Auto-enabled Start/End attempts failed
because command 136 returned an unsuccessful header (`response=0`). The fix
uses `RobotService.set_enable(False, confirmed=True)` only after confirming
Auto mode; Manual still uses DI2. Fresh native status must confirm disabled
before changing mode/DragGo or clearing the latch. A brief status poll no
longer causes a false “mode is already changing” rejection. Regression tests
cover Auto-enabled start/exit, rejected disable, missing state confirmation,
mode changes and poll contention.

```powershell
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_draggo.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_researcher.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/check_researcher_browser.py
```

Linux: use the project's Python environment with the same first two test
commands. The browser test currently launches Windows Edge.
