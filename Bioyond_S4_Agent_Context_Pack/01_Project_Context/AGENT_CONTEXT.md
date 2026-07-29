# Agent Context: Bioyond S4 Autonomous Slide Handler

## Objective

Build a cross-platform host application that coordinates a Bioyond LabGenius S4
robot to move one microscope slide from a known source fixture/slot to a known
destination fixture/slot. The system must verify slide presence, grip status,
release status, and job completion, and must recover safely from communication,
vision, gripper, and controller faults.

The initial implementation should use dummy slides, fixed fixtures, taught robot
points, low speed, and supervised operation. Unattended operation is a later
validation phase.

## Intended architecture

- Bioyond Works on Windows: commissioning, teaching, frames, loads, backups, and
  publishing controller Lua.
- Lua on the S4 controller: validated motion sequences, E1 gripper control,
  sensor checks, completion status, and safe error handling.
- Custom Python host on Windows or Linux: job queue, TCP protocol, persistence,
  Arducam processing, UI/API, identity tracking, and recovery orchestration.
- Hardware E-stop and guarding: authoritative safety controls independent of
  the host application.

The host should send logical commands such as source slot, destination slot,
command, and sequence number. It should not initially stream arbitrary XYZ
coordinates. Lua should map logical locations to taught approach, pick, retreat,
place, and safe points.

## Robot facts

- Platform: Bioyond LabGenius S4.
- Payload: 1.5 kg in the supplied documentation.
- Repeatability: +/-0.02 mm in the supplied documentation.
- Main robot joints: J1-J4.
- External axes displayed by Bioyond Works: E1-E3.
- E1 is normally the Bioyond gripper in this project.
- E2 and E3 are not assumed to exist and must not be commanded unless physically
  installed and configured.
- Digital I/O: 8 DI and 8 DO. Observe the voltage and combined-current limits in
  the hardware manual.

## Safety constraints

- Never override or bypass the E-stop circuit.
- Never use collision detection as the only safeguarding method.
- Never enable automatically after reconnecting or restarting.
- Never blindly repeat a timed-out or disconnected motion command.
- Never begin a new job when the physical state of the preceding job is unknown.
- Do not perform zero calibration unless required and confirmed for the installed
  hardware/firmware.
- Use controller-stored, validated points for the first implementation.
- Validate with plastic/acrylic dummy slides before sacrificial glass slides.
- Limit autonomous retries; uncertain grip, double-pick, drop, and occupied
  destination conditions must enter a controlled error/quarantine state.

## Network and protocol

- The controller is a TCP server and the host is a TCP client.
- Raw BRCAPI port: 56788.
- The raw protocol manual lists a default IP of `192.168.1.220`.
- The supplied C# sample uses `192.168.3.200:56788`.
- Bioyond Works commonly connects to controller `192.168.3.200`.
- Use the actual commissioned address; do not assume all supplied addresses apply
  to the same deployment.
- Only one raw TCP client may be connected at a time.
- Every JSON frame is UTF-8 and terminated by `\n`.
- Requests contain `BRCAPI`, `cmd`, `params`, and integer `id`.
- Responses may include an immediate acknowledgement and a later result/reply.
- Correlate every response by `id`.
- Implement a persistent receive buffer that handles partial frames and multiple
  frames in a single socket read.

Recommended host startup sequence:

1. Connect.
2. Query `getSysState` until initialization completes.
3. Read and report robot errors.
4. Require explicit operator authorization before clearing errors or enabling.
5. Switch to Auto.
6. Enable.
7. Start the Lua application.
8. Wait for `getLuaAppStatus` to report initialized.
9. Submit logical jobs.

## Existing sample variable contract

The supplied integration example uses integer system variables 0-7:

| Index | Meaning |
| ---: | --- |
| 0 | Target device ID |
| 1 | X/location selector |
| 2 | Y/location selector |
| 3 | Z/location selector |
| 4 | Action: 1 pick, 2 place |
| 5 | Object/material type |
| 6 | Point source: 0 controller, 1 host |
| 7 | Motion mode |

Scenario 1 uses controller-stored points. Scenario 2 sends floating-point system
parameters:

| Index | Cartesian use | Joint use |
| ---: | --- | --- |
| 0 | X | J1 |
| 1 | Y | J2 |
| 2 | Z | J3 |
| 3 | Rz | J4 |
| 4 | Speed | Speed percentage |
| 5 | Blend/zone | Blend/zone |
| 6 | E1/gripper position | E1 position |

Scenario 2 sets only X, Y, Z, and Rz; Rx and Ry remain zero and the supplied Lua
uses T0/U0. Do not use it as a general Cartesian-control interface without
explicitly addressing tool/user frames and orientation.

## Recommended application command contract

Freeze a new host/Lua contract before implementation. At minimum it should carry:

- Unique job/sequence number.
- Command (`HOME`, `TRANSFER`, `RECOVER`, `ABORT_SAFE`).
- Source station and slot.
- Destination station and slot.
- Slide/material type.
- Requested options such as identity verification.

Lua should return and persistently expose:

- Sequence number echoed back.
- `IDLE`, `ACCEPTED`, `BUSY`, `DONE`, or `ERROR`.
- Detailed step (`VERIFY_SOURCE`, `PICK`, `VERIFY_GRIP`, `MOVE`, `PLACE`,
  `VERIFY_RELEASE`).
- Error code and recovery requirement.

Write all job fields first and write the sequence/trigger last. Never assume a
timeout means the command was not executed.

## E1 gripper feedback

The supplied Lua runtime exposes:

- `GETJOINTS()._ext1`: actual E1 position.
- `GETREFJOINTS()._ext1`: requested/reference E1 position.
- `GETJOINTSTRQ()._ext1`: E1 torque signal.
- `GETJOINTSNORMTRQ()._ext1`: normalized E1 torque.
- `GRIPPEREMPTYDET(1, torqueThreshold, positionThreshold)`: combines torque and
  target-position error; supplied code returns 1 for holding and 2 for empty.
- `SETEXTJTRQLIMIT` and `MOVEXTJWITHFORCE`: external-axis torque-limited motion.

E1 torque is a controller/motor signal or percentage, not a documented calibrated
force in newtons. Calibrate with dummy slides and a force gauge/load cell. Record
the distributions for empty closure, one slide, and double slide.

The raw `getJointInfo` TCP command returns external-joint position but does not
document torque. Torque/empty detection should therefore run in Lua and report a
simple grip result to the host.

## Required controller points

The final application should have taught and validated points such as:

- `HOME`
- `SOURCE_SAFE`
- `SOURCE_APPROACH`
- `SOURCE_PICK`
- `SOURCE_RETREAT`
- `DEST_SAFE`
- `DEST_APPROACH`
- `DEST_PLACE`
- `DEST_RETREAT`
- `QUARANTINE_APPROACH`
- `QUARANTINE_PLACE`

Travel between stations should occur at a safe elevated plane. Pickup and placement
should use slow, controlled final approaches.

## Suggested persistent job states

- `QUEUED`
- `ACCEPTED`
- `SOURCE_VERIFIED`
- `PICKED`
- `GRIP_VERIFIED`
- `DESTINATION_VERIFIED`
- `PLACED`
- `RELEASE_VERIFIED`
- `COMPLETE`
- `QUARANTINED`
- `FAILED`
- `UNKNOWN_PHYSICAL_STATE`

Persist state after every physical transition so a host restart cannot create a
duplicate pick or placement.

## Known problems in reference software

Do not copy the supplied clients unchanged:

- Python `ModeType` reverses protocol values: protocol is Manual=0, Auto=1.
- Python program-state handling omits Error=3.
- C# and Python assume a socket read contains exactly one JSON frame.
- They do not robustly handle partial/multiple newline frames.
- Receive buffer and cancellation/shutdown behavior are weak.
- Some response paths have race/null-ordering problems.
- Automatic error clearing/retries are not production safe.
- The C# Scenario 1 test has a device-ID mismatch in one command.

## Vision context

The workspace Bioyond vision examples target a HIK/MVS-style camera stack. They
must not be assumed to support an Arducam. The exact Arducam SKU, electrical/data
interface, host platform, driver, and official documentation are still required.

Use vision initially for:

- Source slide present.
- Approximate alignment/orientation.
- Suspected double slide.
- Destination empty/occupied.
- Slide/barcode identity if present.

Transparent slides require controlled lighting; a diffuse backlight or suitable
dark-field arrangement is usually more important than camera resolution.

## Missing deployment inputs

The following are not present in the current workspace and must be supplied before
the application can be finalized:

- Exact S4 serial number, firmware, and Bioyond Works version.
- Actual controller IP used by the raw TCP interface.
- Exact gripper model and fingertip dimensions.
- Slide dimensions, material, label/frosted end, and permitted contact areas.
- Cell photographs and complete physical layout.
- Source/destination fixture drawings or CAD.
- Taught point names and coordinates.
- Sensor/actuator wiring and DI/DO map.
- Measured E1 position/torque distributions.
- Exact Arducam SKU and official documentation.
- Required throughput and traceability.

## Initial validation target

1. One source nest and one destination nest.
2. Dummy slide only.
3. Fixed taught points.
4. Supervised operation at low speed.
5. Source/destination presence verification.
6. E1 one-slide versus empty detection.
7. Persistent job record.
8. Demonstrated safe handling of E-stop, TCP loss, application restart, grip
   failure, occupied destination, and sensor failure.

