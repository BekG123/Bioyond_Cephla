"""S4 Operator Console — human-in-the-loop control panel.

Live eye-in-hand (GigE) camera view + every robot capability as a button:
state control, jog, gripper, and the vision pipeline broken into operator-
triggered stages (Find disk -> Align -> Descend -> Grip -> Lift), each of
which reports back and waits for the human's next decision.

Run:  py operator_ui/app.py   ->  http://127.0.0.1:5002

Exclusivity (one owner at a time, both links):
 - robot TCP: disconnect the MCP server / Bioyond Works first
 - GigE camera: close the MVS client's live view first
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque

from flask import Flask, jsonify, request, Response, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aruco  # noqa: E402
import teach  # noqa: E402
from autonomy import TransferError, validate_request, seq_transfer  # noqa: E402
from camera_service import CameraService  # noqa: E402
from realsense_service import register_realsense  # noqa: E402
from researcher import register_researcher  # noqa: E402
from lacry_backend import LacryBackend  # noqa: E402
from lacry_agent import LacryAgent  # noqa: E402
from classic_pickup import ClassicPickup  # noqa: E402
from researcher_routine_check import check_routine
from researcher_home import HomeReturn  # noqa: E402
from hand_claw import HandClaw  # noqa: E402
from researcher_teaching import StationTeaching  # noqa: E402
from draggo import DragGo  # noqa: E402
from researcher_workflow import PlateTeaching  # noqa: E402
from researcher_descent import ResearcherDescent
from pick_and_hold.Grip.reference_grip import ReferenceGrip
from audit_log import AuditLog, install_audit  # noqa: E402
from imitation_agent import References, ImitationAgent  # noqa: E402
from pickup_planner import PickupPlanner
from researcher_teaching import TeachingError  # noqa: E402
from robot_service import RobotService  # noqa: E402
from pickup import PickupVerification  # noqa: E402
from plate_agent import PlateAgent, VisionClient, AgentError, parse_request as parse_agent_request  # noqa: E402
from credential_store import CredentialStore
from recorded_return import RecordedReturn
from latest_hamilton import LatestHamilton
from coactive_pickup import CoactivePickup
from pick_and_hold.Align.references import ICReferences, ICError  # noqa: E402
from sequences import (  # noqa: E402
    Runner,
    get_robot_params,
    band_floor,
    seq_align,
    seq_calibrate_aruco,
    seq_calibrate_camera,
    seq_descend,
    seq_find_aruco,
    seq_find_disk,
    seq_generate_anchor,
    seq_grip,
    seq_workflow,
)

app = Flask(__name__, static_folder="static")
from lacry_memory import LacryMemory, register_memory_api
lacry_memory = LacryMemory(os.path.join(HERE,'logs','lacry_memory','memory.sqlite3'))
lacry_memory.seed(os.path.join(HERE,'lacry_memory_seed.json'))
register_memory_api(app,lacry_memory)
audit = AuditLog(os.environ.get('CEPHLA_AUDIT_DIR', os.path.join(HERE, 'logs', 'audit')))
install_audit(app, audit)
realsense = register_realsense(app)
svc = RobotService()
svc.audit_sink = audit.event
cam = CameraService()
from developer_diagnostics import DeveloperDiagnostics, register_developer_diagnostics
developer_diagnostics = DeveloperDiagnostics(os.path.join(HERE, 'reports', 'developer_dsl'))
def audit_and_remember(event,**fields):
    developer_diagnostics.observe(event, fields)
    audit.event(event,**fields)
    lacry_memory.observe_event(event,fields,source=str(audit.path))

runner = Runner(event_sink=audit_and_remember, context_provider=audit.context)
pickup = PickupVerification()
plate_agent = PlateAgent(client=VisionClient(store=CredentialStore()))
ic_references = ICReferences()

researcher_teaching = StationTeaching(os.path.join(HERE, 'demonstrations', 'teaching.json'), lambda: svc)
draggo = DragGo(lambda: svc, os.path.join(HERE, 'demonstrations', 'draggo-active.json'))
svc.draggo_guard = draggo
def researcher_calibration(run, service, camera):
    from pick_and_hold.Calibration.fast_disk import run_fast_disk
    return run_fast_disk(run, service, camera, teach, get_robot_params(), config='Wide',
        trace=run.calibration_trace, publish=plate_teaching.publish_guidance)


plate_teaching = PlateTeaching(researcher_teaching, lambda: runner, lambda: cam, lambda: draggo,
    researcher_calibration,
    lambda run, service, target: seq_align(run, service, target, 0, validate_descent=False),
    calibration_logs=os.path.join(HERE, 'reports', 'calibration'))
imitation = ImitationAgent(
    References(researcher_teaching, os.path.join(HERE, 'demonstrations', 'imitation_reference.json'), get_robot_params()),
    plate_agent.client, lambda: svc, lambda: runner, os.path.join(HERE, 'demonstrations'))
home_return = HomeReturn(os.path.join(HERE, 'points.json'), lambda: svc, lambda: runner,
    lambda: draggo, get_robot_params, lambda: (plate_teaching.invalidate(), imitation.invalidate(), pickup.invalidate()),
    prepare=lambda run, service: plate_teaching._prepare(run, service))
hand_claw = HandClaw(lambda: svc, lambda: runner, lambda: draggo, get_robot_params,
                     prepare=lambda run, service: plate_teaching._prepare(run, service))
pickup_planner = PickupPlanner(researcher_teaching, plate_agent.client,
    os.path.join(HERE,'reports','hamilton','teaching_evidence_20261016.json'),
    os.path.join(HERE,'reports','pickup_plans'),get_robot_params,
    lambda:(dict(svc.envelope),svc.envelope_enabled),
    lambda kind, **values:imitation.record(runner,kind,**values))
recorded_return = RecordedReturn(os.path.join(HERE,'demonstrations','return_home_20261016_130748'),
    lambda:svc,lambda:runner,get_robot_params,plate_teaching._prepare,
    lambda:(plate_teaching.invalidate(),imitation.invalidate(),pickup.invalidate()))
latest_hamilton = LatestHamilton(os.path.join(HERE,'demonstrations','return_home_20261016_130748'),
    lambda:svc,lambda:runner,get_robot_params,plate_teaching._prepare,
    lambda:(plate_teaching.invalidate(),imitation.invalidate(),pickup.invalidate()))
coactive_pickup = CoactivePickup(imitation.references, os.path.join(HERE,'demonstrations','coactive_pickup.json'),
    lambda:svc,lambda:runner,imitation.invalidate)
imitation.coactive = coactive_pickup
home_return.hamilton_route = latest_hamilton
position_grip = ReferenceGrip(os.path.join(HERE,'demonstrations','reference_grip'),lambda:svc,lambda:runner)
researcher_descent = ResearcherDescent(lambda:svc, lambda:runner, get_robot_params,
    band_floor, plate_teaching._prepare,position_grip.completed_descent)
from projected_pickup import ProjectedPickup
projected_pickup = ProjectedPickup(researcher_descent,position_grip,lambda:svc,
                                 lambda:runner,get_robot_params,band_floor)
position_grip.plate_configuration = projected_pickup.grip_configuration
lacry_backend = LacryBackend(svc, runner, cam, draggo, home_return, latest_hamilton,
    researcher_descent, position_grip, get_robot_params, band_floor, teach, aruco)
lacry_backend.projected_pickup = projected_pickup
from ik_home import IKHomeConnection
from pickup_home import PickupHome
ik_home_connection = IKHomeConnection(home_return)
pickup_home = PickupHome(ik_home_connection,os.path.join(HERE,'demonstrations','pickup_home'))
classic_pickup = ClassicPickup(researcher_teaching, plate_teaching, researcher_descent,
    position_grip, lambda: svc, lambda: runner, transport=pickup_home)
lacry = LacryAgent(lacry_backend, plate_agent.client, lambda: runner,
    memory=lacry_memory,
    # Same controller bring-up the researcher console ran for every action,
    # here run once a confirmed plan starts, with the step disclosed on the
    # confirmation card.
    prepare=plate_teaching._prepare, home_return=home_return,
    classic_pickup=classic_pickup, reviewed_home=ik_home_connection)
register_researcher(app, lambda: dict(
    robot=svc.status(), camera=cam.info(),
    sequence=dict(active=runner.active or getattr(runner, 'reserved', False))), researcher_teaching, draggo, plate_teaching, imitation, home_return, hand_claw,
    routine_check=lambda saved: check_routine(saved, get_robot_params(), svc.envelope, svc.envelope_enabled),
    pickup_planner=pickup_planner,recorded_return=recorded_return,latest_hamilton=latest_hamilton,descent=researcher_descent,grip=position_grip,
    lacry=lacry)

CAL_PATH = os.path.join(os.path.dirname(HERE), "grab_skill",
                        "calibration.json")

register_developer_diagnostics(app, developer_diagnostics, lambda: runner,
                               lambda: lacry.client, lambda: lacry.credentials)


class TorqueRecorder:
    """Continuous J1-J4/E1 torque sampler for the operator's threshold
    tuning: the human jogs Z manually while this streams readings; the UI
    plots them and the human clicks the deviation value that should trip
    the descent guard. Sampling goes through the same service lock as jog
    commands, so they interleave safely (~1-2 samples/s)."""

    def __init__(self, service) -> None:
        self.svc = service
        self.samples: deque = deque(maxlen=3000)
        self.baseline = None
        self.error = ""
        self._run = False
        self._thread: threading.Thread | None = None

    def start(self) -> dict:
        if self._run:
            return {"ok": True, "note": "already recording"}
        self.samples.clear()
        self.baseline = None
        self.error = ""
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return {"ok": True, "note": "recording — jog Z manually; readings "
                                    "stream to the chart"}

    def stop(self) -> dict:
        self._run = False
        return {"ok": True, "n": len(self.samples)}

    def _loop(self) -> None:
        t0 = time.time()
        warmup = []
        while self._run:
            r = self.svc.torque_report()
            if not r.get("ok"):
                self.error = r.get("error", "torque read failed")
                time.sleep(1.0)
                continue
            self.error = ""
            try:
                z = self.svc.pose_mm()["Z"]
            except Exception:  # noqa: BLE001
                z = None
            j = [r["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
            if self.baseline is None:
                warmup.append(j)
                if len(warmup) >= 3:
                    self.baseline = [sum(v[i] for v in warmup) / len(warmup)
                                     for i in range(4)]
            self.samples.append({"t": round(time.time() - t0, 2), "z": z,
                                 "j": j, "e1t": r.get("e1_torque")})

    def data(self) -> dict:
        return {"ok": True, "recording": self._run, "error": self.error,
                "baseline": self.baseline, "samples": list(self.samples)}


recorder = TorqueRecorder(svc)

# Serialize mutating requests through dispatch. This closes the race between
# a manual command being admitted and a new sequence acquiring ownership.
_dispatch_lock = threading.RLock()


@app.before_request
def command_ownership():
    if request.method != "POST":
        return None
    if request.path == '/agent/settings':
        return None  # API credentials do not move or change the controller, including during DragGo.
    if request.path.startswith('/developer/api/dsl/'):
        return None  # Read-only diagnostics and code previews never dispatch hardware.
    if request.path.startswith('/developer/api/coactive/'):
        if not _dispatch_lock.acquire(blocking=False):
            return jsonify(ok=False, message='Another control is busy. Hold still and capture again.'), 409
        request.environ['bioyond.dispatch_locked'] = True
        return None  # Read/review only, including DragGo; exclude concurrent jog dispatch during capture.
    if request.path == '/researcher/api/latest-hamilton/stop':
        return None  # Queue cancellation must remain available during motion.
    if request.path in ('/researcher/api/imitation/stop', '/researcher/api/home/stop', '/researcher/api/hand-claw/stop', '/researcher/api/recorded-return/stop'):
        return None  # Cancellation must not wait behind motion dispatch.
    if request.path.startswith('/researcher/api/routines/') and request.path.endswith('/pickup-plan'):
        return None  # Log-only analysis owns no controller and invalidates no motion authorization.
    if request.path in ('/researcher/api/run', '/researcher/api/pause', '/researcher/api/stop',
                        '/researcher/api/record', '/researcher/api/save'):
        return None  # Unimplemented playback never forwards robot commands.
    if request.path.startswith('/realsense/'):
        return None  # Independent USB camera/viewer; no robot or GigE access.
    if request.path.startswith('/developer/api/lacry-memory'):
        return None  # Context edits never dispatch motion or change route approvals.
    if request.path == '/pickup/confirm':
        return None  # Token-checked answer only; never commands hardware.
    if request.path in ('/researcher/api/workflow/stop','/researcher/api/descent/stop','/researcher/api/grip/stop'):
        return None  # Requests cancellation only; never starts a movement.
    if request.path in ('/researcher/api/lacry/stop', '/researcher/api/lacry/review',
                        '/researcher/api/lacry/hamilton/abort', '/researcher/api/lacry/hamilton/respond',
                        '/researcher/api/lacry/hamilton/observe',
                        '/researcher/api/lacry/cancel', '/researcher/api/lacry/chat'):
        return None  # Chat can confirm a pending host plan. The agent applies
                     # readiness and runner ownership checks before starting it.
    # Stop/disable must never queue behind a long synchronous manual move.
    emergency = request.path in ("/seq/stop", "/disable", "/torque_rec/stop")
    program_stop = request.path == "/program" and _body().get("action") in ("stop", "pause")
    if emergency or program_stop:
        position_grip.invalidate()
        imitation.invalidate()
        if request.path == '/disable' or program_stop:
            draggo.cancel()
        pickup.invalidate()
        if request.path == "/disable" or program_stop:
            runner.request_stop()
        return None
    if request.path.startswith('/researcher/api/'):
        if not _dispatch_lock.acquire(blocking=False):
            return jsonify(ok=False, message='The arm controls are busy. Wait for the current action to finish, then capture again.'), 409
    else:
        _dispatch_lock.acquire()
    request.environ["bioyond.dispatch_locked"] = True
    if runner.active or getattr(runner, 'reserved', False):
        if request.path.startswith('/researcher/api/'):
            return jsonify(ok=False, message='A lab task is running. Wait for it to finish or press Stop.'), 409
        return jsonify(ok=False, error="A sequence owns the robot/camera/configuration; stop it before changing controls"), 409
    if (request.path not in ('/seq/grip','/connect','/researcher/api/connect')
            and not request.path.startswith('/researcher/api/grip/')
            # A Lacry plan may carry its own descent, or grip a descent the
            # researcher just ran; confirming it must not drop that receipt.
            and not request.path.startswith('/researcher/api/lacry/')):
        position_grip.invalidate()
    if not request.path.startswith(('/researcher/api/imitation/', '/imitation/')):
        imitation.invalidate()
    if request.path.startswith('/researcher/api/'):
        if request.path.startswith(('/researcher/api/hand-guiding/', '/researcher/api/workflow/', '/researcher/api/hand-claw/')):
            pickup.invalidate()
        if request.path == '/researcher/api/hand-guiding/start':
            plate_teaching.invalidate()
        return None
    if draggo.blocks_motion:
        return jsonify(ok=False, error='End hand-guiding in Researcher view before using Developer controls.'), 409
    plate_teaching.invalidate()
    if request.path != '/seq/verify_pickup':
        pickup.invalidate()


@app.teardown_request
def release_command_ownership(_error):
    if request.environ.pop("bioyond.dispatch_locked", False):
        _dispatch_lock.release()


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _refuse_if_sequencing() -> Response | None:
    if runner.active:
        return jsonify({"ok": False, "error":
                        f"sequence '{runner.name}' is running — Stop it "
                        "before manual commands"})
    return None


# ------------------------------------------------------------------ pages

@app.get("/")
@app.get("/researcher")
def index():
    # The researcher-facing site is the Lacry workspace: chat plus the few
    # controls researchers actually press. The stage-by-stage console it
    # replaced is still served below for anyone who needs its detail.
    return send_from_directory(os.path.join(HERE, "static"), "lacry.html")


@app.get("/researcher/classic")
def researcher_classic():
    return send_from_directory(os.path.join(HERE, "static"), "researcher.html")


@app.get("/developer")
def developer():
    return send_from_directory(os.path.join(HERE, "static"), "index.html")


# ----------------------------------------------------------- camera agent

@app.get('/ic/state')
def ic_state():
    return jsonify(**ic_references.public(), active=runner.active and runner.name in ('ic_reference','ic_preview'))


@app.post('/ic/reference/capture')
def ic_capture_reference():
    try:
        options = ic_references.options(_body())
        if recorder._run:
            raise ICError('Stop torque recording before capturing an IC reference')
        if not svc.status().get('connected'):
            raise ICError('Connect the robot for read-only pose recording; this action does not move it')
        return jsonify(runner.start('ic_reference', ic_references.capture, cam, svc.pose_mm, options))
    except (ICError, ValueError, TypeError) as ex:
        return jsonify(ok=False,error=str(ex)),400


@app.post('/ic/reference/select')
def ic_select_reference():
    try:
        return jsonify(ic_references.select(_body().get('id')))
    except (ICError, OSError, ValueError, KeyError) as ex:
        return jsonify(ok=False,error=str(ex)),400


@app.post('/ic/preview')
def ic_preview():
    try:
        identifier=_body().get('id')
        ic_references.load(identifier)
        if recorder._run:
            raise ICError('Stop torque recording before IC preview')
        if not svc.status().get('connected'):
            raise ICError('Connect the robot for read-only pose recording')
        return jsonify(runner.start('ic_preview',ic_references.preview,cam,svc.pose_mm,identifier))
    except (ICError,OSError,ValueError,KeyError) as ex:
        return jsonify(ok=False,error=str(ex)),400


@app.get('/ic/image')
def ic_image():
    try:
        if request.args.get('kind')=='preview':
            path=ic_references.preview_path
            if path is None: raise ICError('No IC preview yet')
        else:
            meta,_=ic_references.load(request.args.get('id'))
            path=ic_references.folder(meta['id'])/'reference_preview.jpg'
        response=send_from_directory(str(path.parent),path.name)
        response.headers['Cache-Control']='no-store'
        return response
    except (ICError,OSError,ValueError,KeyError) as ex:
        return jsonify(ok=False,error=str(ex)),404

@app.get('/agent/state')
def agent_state():
    response = jsonify(**plate_agent.public(), active=runner.active and runner.name == 'camera_agent')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/agent/settings')
def agent_settings():
    try:
        plate_agent.client.set_key(_body().get('api_key', ''))
        return jsonify(ok=True, configured=plate_agent.client.ready(), credential_saved=True)
    except AgentError as ex:
        return jsonify(ok=False, error=str(ex)), 400


@app.get('/imitation/state')
def imitation_state():
    state = imitation.public(developer=True)
    state['pickup_plan'] = pickup_planner.public(developer=True)
    # Full model exchanges already have their own audit events. Polling an
    # unchanged transcript should not copy it into the log every 1.5 seconds.
    if request.args.get('since') == str(state['event_revision']):
        state.update(events=[], unchanged=True)
    response = jsonify(ok=True, **state)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/developer/api/coactive')
def coactive_state():
    return jsonify(coactive_pickup.public())


@app.post('/developer/api/coactive/<action>')
def coactive_action(action):
    try:
        if action == 'capture':
            result = coactive_pickup.capture(_body())
        elif action == 'decide':
            result = coactive_pickup.decide(_body())
        else:
            return jsonify(ok=False, message='Unknown learning action.'), 404
        audit.event('coactive_' + action, result=result)
        return jsonify(result)
    except TeachingError as error:
        return jsonify(ok=False, message=str(error)), error.status
    except (OSError, ValueError, KeyError, TypeError):
        app.logger.exception('Coactive pickup storage or measurement failed')
        return jsonify(ok=False, message='Correction could not be saved. Check Developer logs.'), 503


@app.get('/imitation/reference')
def imitation_reference():
    try:
        return jsonify(ok=True, reference=imitation.references.candidate(request.args.get('source_id')))
    except TeachingError as error:
        return jsonify(ok=False, error=str(error)), error.status
    except (OSError, ValueError, KeyError):
        return jsonify(ok=False, error='Teaching data needs developer attention.'), 503


@app.post('/imitation/reference')
def approve_imitation_reference():
    try:
        reference = imitation.references.approve(_body())
        imitation.invalidate()
        audit.event('imitation_reference_reviewed', reference=reference)
        return jsonify(ok=True, reference=reference)
    except TeachingError as error:
        return jsonify(ok=False, error=str(error)), error.status
    except (OSError, ValueError, KeyError):
        return jsonify(ok=False, error='Reference could not be saved. Check teaching data and storage.'), 503


@app.post('/agent/run')
def agent_run():
    try:
        config = parse_agent_request(_body())
        if config['mode'] == 'analyze' and not plate_agent.client.ready():
            raise AgentError('Add the vision API key in Camera agent settings')
        if recorder._run:
            raise AgentError('Stop torque recording before running the camera agent')
    except AgentError as ex:
        return jsonify(ok=False, error=str(ex)), 400
    return jsonify(runner.start('camera_agent', plate_agent.execute,
                                cam, svc.status, config))


@app.get('/agent/image')
def agent_image():
    path = plate_agent.depth_path if request.args.get('kind') == 'depth' else plate_agent.image_path
    if not path:
        return jsonify(error='No agent image yet'), 404
    response = send_from_directory(os.path.dirname(path), os.path.basename(path))
    response.headers['Cache-Control'] = 'no-store'
    return response


# ----------------------------------------------------------------- camera

@app.get('/agent/training')
def agent_training():
    return send_from_directory(HERE, 'DEPTH_TRAINING.md', mimetype='text/plain')

@app.get("/frame")
def frame():
    jpeg, err = cam.frame_jpeg()
    if jpeg is None:
        return jsonify({"error": err or "no frame yet"}), 503
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Error"] = err
    return resp

@app.get("/crop")
def crop():
    cx = int(request.args.get("cx", 0))
    cy = int(request.args.get("cy", 0))
    size = max(60, min(800, int(request.args.get("size", 240))))
    jpeg = cam.crop_jpeg(cx, cy, size)
    if jpeg is None:
        return jsonify({"error": "no frame captured yet"}), 503
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.post("/camera/release")
def camera_release():
    cam.release()
    return jsonify({"ok": True, "note": "camera released for MVS/other apps"})

@app.post("/camera/resume")
def camera_resume():
    cam.resume()
    return jsonify({"ok": True})

@app.post("/camera/snapshot")
def camera_snapshot():
    try:
        path = cam.save(prefix="snap")
        return jsonify({"ok": True, "path": path})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


# ------------------------------------------------------------------ state

@app.get("/state")
def state():
    return jsonify({
        "robot": svc.status(),
        "envelope": svc.envelope_dict(),
        "camera": cam.info(),
        "sequence": {"state": runner.state, "name": runner.name,
                     "active": runner.active or getattr(runner, 'reserved', False)},
        "target": runner.target,
        "ts": time.time(),
    })

@app.get("/seq")
def seq():
    return jsonify(runner.snapshot())

@app.get("/developer/api/lua/diagnostics")
def lua_diagnostics():
    # Queries only: never starts/stops a program or triggers a Lua job.
    if runner.active:
        return jsonify(ok=False, error='Wait for the active sequence before Lua diagnostics.'), 409
    return jsonify(svc.lua_diagnostics())

@app.post("/developer/api/grip/empty-baseline")
def empty_grip_baseline():
    b=_body()
    local=set(b)=={'empty','ready','start_mm'} and b['empty'] is True and b['ready'] is True
    if not local and b not in ({'empty': True, 'ready': True},
                              {'empty': True, 'ready': True, 'short': True}):
        return jsonify(ok=False,error='Confirm empty open claw, hands clear and E-stop supervised.'),400
    from empty_grip_baseline import run_empty_baseline,finite
    try:
        start=finite(b['start_mm']) if local else 28.
        if not 3.8 < start <= 28 or abs(start*10-round(start*10))>1e-6:
            raise ValueError('Baseline start must be on the 0.1 mm grid above 3.8 mm.')
    except (ValueError,TypeError) as error:
        return jsonify(ok=False,error=str(error)),400
    refusal=svc._preflight()
    if refusal:return jsonify(ok=False,error=refusal),409
    return jsonify(runner.start('empty_grip_baseline',run_empty_baseline,svc,
                               os.path.join(HERE,'demonstrations','empty_grip_baseline'), b.get('short',False),start))

@app.post("/developer/api/grip/supervised-batch")
def supervised_grip_batch():
    b=_body()
    allowed=({'plate_centered','ready','start_mm'},
             {'plate_centered','ready','start_mm','use_labeled_noncontact'})
    if (set(b) not in allowed or b['plate_centered'] is not True or b['ready'] is not True
            or ('use_labeled_noncontact' in b and b['use_labeled_noncontact'] is not True)):
        return jsonify(ok=False,error='Confirm centered plate, hands clear and supervised E-stop.'),400
    from supervised_grip_batch import run_batch
    refusal=svc._preflight()
    if refusal:return jsonify(ok=False,error=refusal),409
    try:
        start=float(b['start_mm'])
        if not 5 < start <= 28 or abs(start*10-round(start*10))>1e-6:
            raise ValueError('Start must be on the 0.1 mm grid above 5 mm.')
    except (TypeError,ValueError,OverflowError) as error:
        return jsonify(ok=False,error=str(error)),400
    return jsonify(runner.start('supervised_grip_batch',run_batch,svc,start,band_floor(),
                               b.get('use_labeled_noncontact',False)))


@app.get("/robot_params")
def robot_params():
    """Kinematic constants (link lengths, base offset) for the 3D View tab
    to draw the arm and mirror the server's planar IK client-side."""
    return jsonify(get_robot_params())

@app.get("/teach_view")
def teach_view():
    p = runner.detection_path
    if not p or not os.path.exists(p):
        return jsonify({"error": "no detection image"}), 404
    with open(p, "rb") as f:
        resp = Response(f.read(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------- connection

@app.post("/connect")
def connect():
    return jsonify(svc.connect(_body().get("ip", "")))

@app.post("/disconnect")
def disconnect():
    return jsonify(svc.disconnect())


# ------------------------------------------------------------ state ctrl

@app.post("/mode")
def mode():
    return jsonify(svc.switch_mode(_body().get("mode", "auto")))

@app.post("/enable")
def enable():
    b = _body()
    return jsonify(svc.set_enable(True, bool(b.get("confirm"))))

@app.post("/disable")
def disable():
    return jsonify(svc.set_enable(False, True))

@app.post("/clear_errors")
def clear_errors():
    return jsonify(svc.clear_errors(bool(_body().get("confirm"))))

@app.post("/program")
def program():
    b = _body()
    return jsonify(svc.program(b.get("action", ""), bool(b.get("force"))))

@app.post("/envelope/enable")
def envelope_enable():
    return jsonify(svc.set_envelope_enabled(bool(_body().get("enabled"))))

@app.post("/envelope")
def envelope():
    b = _body()
    try:
        return jsonify(svc.set_envelope(
            float(b["x_min"]), float(b["x_max"]),
            float(b["y_min"]), float(b["y_max"]),
            float(b["z_min"]), float(b["z_max"])))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad envelope values: {ex}"})


# ----------------------------------------------------------------- motion

@app.post("/jog")
def jog():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    try:
        return jsonify(svc.jog(str(b["axis"]), float(b["delta"]),
                               float(b.get("speed", 0))))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad jog request: {ex}"})

@app.post("/move")
def move():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    try:
        return jsonify(svc.move_cartesian(
            float(b["x"]), float(b["y"]), float(b["z"]), float(b["rz"]),
            float(b.get("speed", 0)), b.get("interpolation", "linear")))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad move request: {ex}"})

@app.post("/lift")
def lift():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    z = float(b.get("z", 150.0))
    if z <= pose["Z"]:
        return jsonify({"ok": False, "error":
                        f"lift target Z {z} is not above current Z "
                        f"{pose['Z']}"})
    res = svc.move_cartesian(pose["X"], pose["Y"], z, pose["Rz"],
                             10.0, "linear")
    if res.get("ok"):
        res["gripper_after"] = svc.gripper_status()
    return jsonify(res)


# ---------------------------------------------------------------- gripper

@app.post("/gripper")
def gripper():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    action = b.get("action", "")
    if action == "status":
        return jsonify(svc.gripper_status())
    if action == "torque":
        return jsonify(svc.torque_report())
    if action == "move":
        try:
            return jsonify(svc.move_gripper(float(b["e1"]),
                                            float(b.get("speed", 0))))
        except (KeyError, ValueError) as ex:
            return jsonify({"ok": False, "error": f"bad gripper move: {ex}"})
    return jsonify({"ok": False, "error": f"unknown gripper action "
                    f"'{action}'"})


# ----------------------------------------------------- z-cal + torque tab

@app.get("/zcal")
def zcal_get():
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        return jsonify({"ok": True,
                        "z_touch_offset_mm": c["z_touch_offset_mm"],
                        "safety_margin_mm": c["safety_margin_mm"],
                        "grip_extra_mm": c["z_touch_offset_mm"]
                        + c["safety_margin_mm"]})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


@app.post("/zcal")
def zcal_set():
    b = _body()
    try:
        off = float(b["z_touch_offset_mm"])
        mar = float(b.get("safety_margin_mm", 0.0))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad values: {ex}"})
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        c.setdefault("history", []).append(
            {"date": time.strftime("%Y-%m-%d %H:%M"),
             "source": "operator UI edit",
             "offset": off, "margin": mar})
        c["z_touch_offset_mm"] = off
        c["safety_margin_mm"] = mar
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
        # keep the running solvers in sync (they cached the value at import)
        aruco.Z_TOUCH = off + mar
        aruco.W.Z_TOUCH = off + mar
        return jsonify({"ok": True, "z_touch_offset_mm": off,
                        "safety_margin_mm": mar, "grip_extra_mm": off + mar,
                        "note": "saved to grab_skill/calibration.json — "
                                "used by the NEXT Find; an already-published "
                                "target keeps its old grip Z"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


@app.post("/marker_offset")
def marker_offset_save():
    """Learn the per-marker grasp correction from the CURRENT claw
    position: the operator aligns/jogs until the claw is visually perfect
    over the object, then presses Save. offset = claw_world − marker_world
    rotated into the MARKER frame, so it holds at any object rotation."""
    import math as _m
    t = runner.target or {}
    if "marker_world" not in t or "marker_yaw" not in t:
        return jsonify({"ok": False, "error": "no ArUco target with marker "
                        "pose — run Find ArUco first"})
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    a = _m.radians(pose["Rz"])
    arm = aruco.CLAW_ARM
    claw_x = pose["X"] + arm[0] * _m.cos(a) - arm[1] * _m.sin(a)
    claw_y = pose["Y"] + arm[0] * _m.sin(a) + arm[1] * _m.cos(a)
    mw = t["marker_world"]
    dxw, dyw = claw_x - float(mw[0]), claw_y - float(mw[1])
    if _m.hypot(dxw, dyw) > 40.0:
        return jsonify({"ok": False, "error":
                        f"claw is {_m.hypot(dxw, dyw):.0f} mm from the "
                        "marker — that is not a small correction; re-run "
                        "Find ArUco instead"})
    y = _m.radians(float(t["marker_yaw"]))
    dx = dxw * _m.cos(-y) - dyw * _m.sin(-y)
    dy = dxw * _m.sin(-y) + dyw * _m.cos(-y)
    mid = str(t.get("marker_id", "?"))
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        c.setdefault("marker_offsets", {})[mid] = {
            "dx_mm": round(dx, 2), "dy_mm": round(dy, 2),
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "note": "learned from operator jog in the UI"}
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
        aruco.W.CAL.setdefault("marker_offsets", {})[mid] = \
            c["marker_offsets"][mid]
        return jsonify({"ok": True, "marker_id": mid,
                        "offset_marker_frame_mm": [round(dx, 2),
                                                   round(dy, 2)],
                        "note": "every future Find ArUco applies this "
                                "automatically (any object rotation)"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


_claw_arm_pending: dict | None = None


@app.post("/claw_arm_save")
def claw_arm_save():
    """TWO-SIDED claw calibration (bias-immune). Press once with the claw
    midpoint jogged exactly onto the last Find's marker; ROTATE the wrist
    ~180 deg, jog the claw onto the marker again, press again — the two
    measurements separate the true arm from the camera-solve bias (one
    measurement alone bakes the bias in, and a grab at the flipped wrist
    side then misses by twice the error — observed live 2026-07-25)."""
    global _claw_arm_pending
    import math as _m
    t = runner.target or {}
    if "marker_world" not in t:
        return jsonify({"ok": False, "error": "no ArUco target with marker "
                        "pose — run Find ArUco first"})
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    mw = t["marker_world"]
    dxw, dyw = float(mw[0]) - pose["X"], float(mw[1]) - pose["Y"]
    a = _m.radians(-pose["Rz"])
    meas = [dxw * _m.cos(a) - dyw * _m.sin(a),
            dxw * _m.sin(a) + dyw * _m.cos(a)]
    if _claw_arm_pending is None or _claw_arm_pending.get(
            "marker") != list(mw):
        _claw_arm_pending = {"meas": meas, "rz": pose["Rz"],
                             "marker": list(mw)}
        return jsonify({"ok": True, "step": "1 of 2",
                        "measurement": [round(v, 2) for v in meas],
                        "rz": pose["Rz"],
                        "note": "measurement 1 stored. Now ROTATE the "
                                "wrist ~180 deg (any >=30), jog the claw "
                                "back onto the SAME marker, press again."})
    dth = abs((pose["Rz"] - _claw_arm_pending["rz"] + 180.0) % 360.0
              - 180.0)
    if dth < 30.0:
        _claw_arm_pending = {"meas": meas, "rz": pose["Rz"],
                             "marker": list(mw)}
        return jsonify({"ok": True, "step": "1 of 2 (replaced)",
                        "note": f"wrist only moved {dth:.0f} deg since "
                                "measurement 1 — need >= 30 (ideally "
                                "~180). Measurement replaced; rotate and "
                                "press again."})
    arm, cbias = aruco.W.solve_claw_arm_two(
        _claw_arm_pending["meas"], _claw_arm_pending["rz"],
        meas, pose["Rz"])
    old = list(aruco.CLAW_ARM)
    saved = aruco.save_claw_arm(list(arm),
                                f"two-sided jog calibration (dth "
                                f"{dth:.0f} deg)")
    _claw_arm_pending = None
    return jsonify({"ok": True, "step": "2 of 2 — SAVED",
                    "claw_arm_tool_mm": saved,
                    "previous": [round(v, 2) for v in old],
                    "camera_bias_measured_mm": [round(float(cbias[0]), 2),
                                                round(float(cbias[1]), 2)],
                    "note": "arm updated (bias-separated). CLEAR any "
                            "jog-saved marker offsets recorded under the "
                            "old arm and re-trim/1c if needed."})


@app.post("/anchor_confirm")
def anchor_confirm():
    """Operator verdict on a finished Generate-anchor run: save the
    pending anchor rows, or discard them. The sequence itself never
    writes — a bad convergence must not become ground truth."""
    b = _body()
    res = runner.result or {}
    if not res.get("anchor_pending"):
        return jsonify({"ok": False, "error": "no pending anchor — run "
                        "Generate anchor first"})
    if not b.get("save"):
        res["anchor_pending"] = False
        res["anchor_discarded"] = True
        return jsonify({"ok": True, "note": "anchor DISCARDED — nothing "
                        "was written; rerun Generate anchor when ready"})
    n = 0
    for row in res.get("pending_rows", []):
        n = aruco.save_anchor(row)
    res["anchor_pending"] = False
    res["anchor_saved_total"] = n
    return jsonify({"ok": True, "anchors_total": n,
                    "note": "anchor saved (2 rows) — Calibrate camera now "
                            "auto-re-derives the claw arm from stored "
                            "anchors after every refit"})


@app.post("/marker_offset_clear")
def marker_offset_clear():
    """Remove the learned offset for the last Find's marker id (or a
    given id) — use after recalibrating the claw arm, since jog-saved
    offsets recorded under a wrong arm are contaminated."""
    b = _body()
    t = runner.target or {}
    mid = str(b.get("marker_id", t.get("marker_id", "")))
    if not mid:
        return jsonify({"ok": False, "error": "no marker id — run Find "
                        "ArUco first or pass marker_id"})
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        entry = c.get("marker_offsets", {}).pop(mid, None)
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
        aruco.W.CAL.get("marker_offsets", {}).pop(mid, None)
        return jsonify({"ok": True, "marker_id": mid,
                        "removed": entry,
                        "note": "offset cleared — grabs now target the "
                                "marker itself; re-run 1c Calibrate disk "
                                "ID (or jog-trim) to relearn"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


@app.post("/wrist_rel_save")
def wrist_rel_save():
    """New-arm clamp-orientation calibration: with the plates visually
    parallel to the object's long edges, save rz - marker_yaw."""
    import math as _m  # noqa: F401
    t = runner.target or {}
    if "marker_yaw" not in t:
        return jsonify({"ok": False, "error": "no ArUco target with marker "
                        "yaw — run Find ArUco first"})
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    rel = (pose["Rz"] - float(t["marker_yaw"]) + 180.0) % 360.0 - 180.0
    saved = aruco.save_wrist_rel(rel)
    return jsonify({"ok": True, **saved,
                    "note": "grab candidates now use this relation "
                            "(mod 180 — claw is symmetric)"})


@app.post("/torque_rec/start")
def torque_rec_start():
    r = _refuse_if_sequencing()
    if r:
        return r
    return jsonify(recorder.start())


@app.post("/torque_rec/stop")
def torque_rec_stop():
    return jsonify(recorder.stop())


@app.get("/torque_rec/data")
def torque_rec_data():
    return jsonify(recorder.data())


@app.get("/torque_threshold")
def torque_threshold_get():
    from sequences import band_floor
    return jsonify({"ok": True, "band_counts": band_floor()})


@app.post("/torque_threshold")
def torque_threshold_set():
    b = _body()
    try:
        v = float(b["band_counts"])
        if not (5.0 <= v <= 500.0):
            return jsonify({"ok": False, "error": "threshold must be "
                            "5..500 counts"})
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad threshold: {ex}"})
    from sequences import TORQUE_CFG_PATH
    with open(TORQUE_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({"band_counts": v,
                   "set_at": time.strftime("%Y-%m-%d %H:%M"),
                   "source": "operator torque-feedback tab"}, f, indent=1)
    return jsonify({"ok": True, "band_counts": v,
                    "note": "descent guard now trips at this deviation "
                            "(per joint, replacing the default ±25 floor)"})


# -------------------------------------------------------------- sequences

@app.get("/transfer/config")
def transfer_config():
    return jsonify(ok=True, markers=aruco.W.CAL.get("marker_offsets", {}),
                   model_stamps=aruco.model_stamps(),
                   marker_size_mm=aruco.MARKER_SIZE_MM,
                   note="One supervised cycle, starting with the marker centered in the eye camera. Destination is TCP, not plate center.")


@app.post("/seq/transfer")
def transfer_start():
    return jsonify(ok=False, error='Pickup transfer is unavailable while Grip control is being replaced.'), 410


@app.post("/seq/transfer_preview")
def transfer_preview():
    try:
        config = validate_request(_body(), preview=True)
    except TransferError as ex:
        return jsonify(ok=False, error=str(ex)), 400
    if recorder._run:
        return jsonify(ok=False, error="Stop torque recording before preview"), 409
    return jsonify(runner.start("aruco_transfer_preview", seq_transfer, svc,
                                cam, aruco, config, get_robot_params()))

@app.post("/seq/find_disk")
@app.post("/seq/find_disk_original")
def seq_find_original():
    from sequences_original import seq_find_disk as original_find_disk
    body = _body()
    if any(body.get(key) is not True for key in ("confirm", "cell_clear", "empty_gripper")):
        return jsonify(ok=False, error="Confirm E-stop supervision, clear swept volume and empty gripper before original two-circle calibration"), 400
    if recorder._run:
        return jsonify(ok=False, error="Stop torque recording before calibration"), 409
    return jsonify(runner.start("find_disk", original_find_disk, svc, cam, teach))


@app.post("/seq/find_disk_fast")
def seq_find():
    body = _body()
    if any(body.get(key) is not True for key in ("confirm", "cell_clear", "empty_gripper")):
        return jsonify(ok=False, error="Confirm supervision at E-stop, clear camera-motion "
                       "swept volume, and an empty gripper before Fast calibrate disk"), 400
    return jsonify(runner.start("find_disk", seq_find_disk, svc, cam, teach))


@app.post("/seq/preview_plate_edges")
def preview_plate_edges():
    from edge_center import preview
    return jsonify(runner.start('preview_plate_edges',preview,cam))


@app.post('/seq/projected_disk_pilot')
def projected_disk_pilot_route():
    from projected_disk_trial import pilot, validate_request as validate_pilot
    try:
        config=validate_pilot(_body())
    except TransferError as ex:
        return jsonify(ok=False,error=str(ex)),400
    if recorder._run:
        return jsonify(ok=False,error='Stop torque recording before the projected-disk pilot'),409
    return jsonify(runner.start('projected_disk_pilot',pilot,svc,cam,get_robot_params(),config))


@app.post('/seq/projected_height_pilot')
def projected_height_pilot_route():
    from projected_height_trial import pilot, validate_request as validate_height
    try:
        config=validate_height(_body())
    except TransferError as ex:
        return jsonify(ok=False,error=str(ex)),400
    if recorder._run:
        return jsonify(ok=False,error='Stop torque recording before the height pilot'),409
    return jsonify(runner.start('projected_height_pilot',pilot,svc,cam,get_robot_params(),config))


@app.post('/seq/projected_alignment')
def projected_alignment_route():
    from projected_alignment import align, validate_request
    try:
        config=validate_request(_body())
    except TransferError as ex:
        return jsonify(ok=False,error=str(ex)),400
    if recorder._run:
        return jsonify(ok=False,error='Stop torque recording before projected alignment'),409
    return jsonify(runner.start('projected_alignment',align,svc,cam,get_robot_params(),config))


@app.get('/researcher/api/projected-pickup')
def projected_pickup_status():
    return jsonify(projected_pickup.public())


@app.post('/seq/projected_descent_trial')
def projected_descent_trial_route():
    from researcher_teaching import TeachingError
    try:
        return jsonify(projected_pickup.start_trial(_body()))
    except (TeachingError,TransferError) as error:
        return jsonify(ok=False,error=str(error)),400


@app.post('/researcher/api/projected-pickup/accept-descent')
def projected_descent_acceptance_route():
    from researcher_teaching import TeachingError
    try:
        return jsonify(projected_pickup.accept_descent(_body()))
    except (TeachingError,TransferError) as error:
        return jsonify(ok=False,error=str(error)),400


@app.post("/seq/center_plate_edges")
def center_plate_edges():
    from edge_center import center, validate_request as validate_edges
    try:
        config=validate_edges(_body())
    except TransferError as ex:
        return jsonify(ok=False,error=str(ex)),400
    if recorder._run:
        return jsonify(ok=False,error='Stop torque recording before centering'),409
    return jsonify(runner.start('center_plate_edges',center,svc,cam,get_robot_params(),config))


@app.post("/seq/find_aruco")
def seq_find_aruco_route():
    return jsonify(runner.start("find_aruco", seq_find_aruco, svc, cam,
                                aruco, _body().get("marker_id")))


@app.post("/seq/calibrate_aruco")
def seq_calibrate_aruco_route():
    return jsonify(runner.start("calibrate_aruco", seq_calibrate_aruco,
                                svc, cam, aruco, _body().get("marker_id")))


@app.post("/seq/calibrate_camera")
def seq_calibrate_camera_route():
    return jsonify(runner.start("calibrate_camera", seq_calibrate_camera,
                                svc, cam, aruco))


@app.post("/seq/generate_anchor")
def seq_generate_anchor_route():
    return jsonify(runner.start("generate_anchor", seq_generate_anchor,
                                svc, cam, teach, aruco))


# ------------------------------------------------- saved points + workflow

POINTS_PATH = os.path.join(HERE, "points.json")


def _points_load() -> dict:
    try:
        d = json.load(open(POINTS_PATH, encoding="utf-8-sig"))
        d.setdefault("points", {})
        d.setdefault("roles", {})
        return d
    except Exception:  # noqa: BLE001
        return {"points": {}, "roles": {}}


def _points_store(d: dict) -> None:
    with open(POINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


@app.get("/points")
def points_get():
    return jsonify({"ok": True, **_points_load()})


@app.post("/points/save")
def points_save():
    """Save a named point from EXPLICIT values — the browser sends the
    grasp-target fields (x, y, rz, z_grip), so whatever Find published
    (or the operator typed into the fields) is exactly what is stored.
    Falls back to the current pose when no values are sent."""
    b = _body()
    name = str(b.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "give the point a name"})
    try:
        if all(b.get(k) is not None for k in ("x", "y", "rz", "z_grip")):
            pt = {"x": float(b["x"]), "y": float(b["y"]),
                  "rz": float(b["rz"]), "z_grip": float(b["z_grip"])}
            src = "target fields"
        else:
            pose = svc.pose_mm()
            pt = {"x": pose["X"], "y": pose["Y"], "rz": pose["Rz"],
                  "z_grip": pose["Z"]}
            src = "current pose"
    except (TypeError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad values: {ex}"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    pt = {k: round(float(v), 3) for k, v in pt.items()}
    pt["saved_at"] = time.strftime("%H:%M:%S")
    d = _points_load()
    d["points"][name] = pt
    _points_store(d)
    return jsonify({"ok": True, "point": pt, "name": name,
                    "z_source": src, "count": len(d["points"])})


@app.post("/points/order")
def points_order():
    """Persist the operator's travel-leg motion order (z / rz / xy / x /
    y tokens). Validated by the same parser the workflow uses."""
    from sequences import _parse_order
    b = _body()
    s = str(b.get("order", "")).strip()
    toks, err = _parse_order(s or "z,rz,xy")
    if toks is None:
        return jsonify({"ok": False, "error": err})
    d = _points_load()
    d["motion_order"] = s or "z,rz,xy"
    _points_store(d)
    return jsonify({"ok": True, "motion_order": d["motion_order"],
                    "resolved": toks})


@app.post("/points/delete")
def points_delete():
    b = _body()
    name = str(b.get("name", "")).strip()
    d = _points_load()
    if name not in d["points"]:
        return jsonify({"ok": False, "error": f"no point named '{name}'"})
    del d["points"][name]
    d["roles"] = {r: n for r, n in d["roles"].items() if n != name}
    _points_store(d)
    return jsonify({"ok": True, "count": len(d["points"])})


@app.post("/points/role")
def points_role():
    b = _body()
    role = str(b.get("role", "")).strip()
    name = str(b.get("name", "")).strip()
    if role not in ("start", "end", "home"):
        return jsonify({"ok": False, "error": "role must be "
                                              "start/end/home"})
    d = _points_load()
    if name and name not in d["points"]:
        return jsonify({"ok": False, "error": f"no point named '{name}'"})
    if name:
        d["roles"][role] = name
    else:
        d["roles"].pop(role, None)
    _points_store(d)
    return jsonify({"ok": True, "roles": d["roles"]})


@app.post("/seq/workflow")
def seq_workflow_route():
    return jsonify(ok=False, error='Pickup workflow is unavailable while Grip control is being replaced.'), 410

@app.post("/seq/align")
def seq_align_route():
    b = _body()
    tgt = _target_from(b)
    if tgt is None:
        return jsonify({"ok": False, "error": "no grasp target — run Find "
                        "disk first (or fill the target fields)"})
    return jsonify(runner.start("align", seq_align, svc, tgt,
                                float(b.get("hover_z", 0) or 0)))

@app.post("/seq/descend")
def seq_descend_route():
    tgt = _target_from(_body())
    if tgt is None:
        return jsonify({"ok": False, "error": "no grasp target — run Find "
                        "disk first (or fill the target fields)"})
    return jsonify(runner.start("descend", seq_descend, svc, tgt))

@app.post("/seq/grip")
def seq_grip_route():
    from researcher_teaching import TeachingError
    try:
        return jsonify(position_grip.start(_body()))
    except TeachingError as error:
        return jsonify(ok=False,error=str(error)),error.status


@app.post("/seq/descend_lua")
def seq_descend_lua_route():
    from pick_and_hold.Descend.lua_executor import seq_descend_lua
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    tgt = _target_from(_body())
    if tgt is None:
        return jsonify({"ok": False, "error": "Run calibration and Align before Lua descent."})
    return jsonify(runner.start("descend_lua", seq_descend_lua, svc, tgt))

@app.post("/seq/stop")
def seq_stop():
    return jsonify(runner.request_stop())


@app.post('/developer/api/scope-compact40/return-home')
def scope_compact40_return_home():
    from scope_compact_trial import review, execute
    if _body() != {'ready':True}:
        return jsonify(ok=False,error='Confirm new reverse corridor clear, arm released and E-stop supervised.'),400
    try:
        cfg=get_robot_params()
        plan=review(svc,cfg)
        return jsonify(runner.start('scope_compact40_return_home',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/scope-compact40/to-scope')
def scope_compact40_to_scope():
    from scope_compact_trial import review_forward, execute_forward
    if _body() != {'ready':True}:
        return jsonify(ok=False,error='Require cleared Home to scope corridor, arm released and E-stop supervised.'),400
    try:
        cfg=get_robot_params()
        plan=review_forward(svc,cfg)
        return jsonify(runner.start('scope_compact40_to_scope',execute_forward,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/scope-compact137/roundtrip')
def scope_compact137_roundtrip():
    from scope_compact137 import review, execute
    if _body() != {'ready':True}:
        return jsonify(ok=False,error='Require the cleared scope/Home round trip and supervised speed-137 test.'),400
    try:
        cfg=get_robot_params()
        plan=review(svc,cfg)
        return jsonify(runner.start('scope_compact137_roundtrip',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/scope-step40/start')
def scope_step40_start():
    from scope_step_trial import review, execute
    body=_body()
    if body != {'ready':True}:
        return jsonify(ok=False,error='Confirm the new Home connector and taught route clear, arm released and E-stop supervised.'),400
    try:
        cfg=get_robot_params()
        plan=review(svc,cfg)
        return jsonify(runner.start('scope_step40',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/loaded-home137/start')
def loaded_home137_start():
    from loaded_home_trial import review, execute, OUTPUT
    if _body().get('ready') is not True:
        return jsonify(ok=False,error='Confirm the loaded round-trip route and supervised run.'),400
    try:
        if set(_body())-{'ready','repeat_of'}:
            raise ValueError('Only readiness and the completed trial reference are accepted.')
        cfg=get_robot_params()
        repeat_of=_body().get('repeat_of')
        output=OUTPUT.with_name(f'loaded_roundtrip_137_replay_{time.time_ns()}.json') if repeat_of else OUTPUT
        plan=review(svc,cfg,output,repeat_of)
        return jsonify(runner.start('loaded_home137',execute,svc,cfg,plan,output,repeat_of))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/seq/verify_pickup')
def verify_pickup_route():
    return jsonify(ok=False, error='Pickup verification is unavailable while Grip control is being replaced.'), 410


@app.post('/developer/api/staged-lift-3p7/start')
def staged_lift_3p7_start():
    from staged_lift_trial import review, execute
    if _body() != {'ready':True}:
        return jsonify(ok=False,error='Confirm the supervised two-stage upward lift.'),400
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    try:
        cfg = get_robot_params()
        approved = review(svc,cfg)
        return jsonify(runner.start('staged_lift_3p7',execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/hamilton-reteach/start')
def hamilton_reteach_start():
    from hamilton_reteach_trial import SHA,review,execute
    body=_body();direction=body.get('direction','forward')
    if (direction not in ('forward','reverse') or body.get('ready') is not True
            or body.get('candidate_sha256')!=SHA or set(body)-{'ready','candidate_sha256','direction'}):
        return jsonify(ok=False,error='Confirm the exact revised Hamilton trial and clear supervised route.'),400
    try:
        cfg=get_robot_params();plan=review(svc,cfg,reverse=direction=='reverse')
        return jsonify(runner.start('hamilton_reteach',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/squid-48well-trial/start')
def squid_48well_endpoint_start():
    from squid_48well_endpoint_trial import SHA,review,execute
    body=_body()
    if body!={'ready':True,'candidate_sha256':SHA}:
        return jsonify(ok=False,error='Confirm the exact revised Squid trial and supervised clear route.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg)
        return jsonify(runner.start('squid_48well_endpoint_trial',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/squid-48well-retrieval/start')
def squid_48well_retrieval_start():
    from squid_48well_retrieval_trial import SHA,review,execute
    body=_body()
    if (body.get('ready') is not True or body.get('candidate_sha256')!=SHA
            or set(body)-{'ready','candidate_sha256','stop_before_release'}
            or type(body.get('stop_before_release',False)) is not bool):
        return jsonify(ok=False,error='Confirm exact supervised 48-well retrieval.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg,stop_before_release=body.get('stop_before_release',False))
        return jsonify(runner.start('squid_48well_retrieval',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/regrip-lift-3p7/start')
def regrip_lift_3p7_start():
    from regrip_lift_trial import review, execute
    body = _body()
    if body.get('ready') is not True or set(body)-{'ready','opening_mm'}:
        return jsonify(ok=False,error='Require the supervised replace, regrip and lift trial.'),400
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    try:
        cfg = get_robot_params()
        approved = review(svc,cfg,body.get('opening_mm',5.0))
        return jsonify(runner.start('regrip_lift_3p7',execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.get('/pickup/state')
def pickup_state():
    response=jsonify(pickup.public());response.headers['Cache-Control']='no-store';return response


@app.post('/pickup/confirm')
def pickup_confirm():
    try:
        pickup.confirm(_body().get('token'),_body().get('confirmed'))
        return jsonify(ok=True)
    except TransferError as ex:
        return jsonify(ok=False,error=str(ex)),400


@app.get('/pickup/image/<which>')
def pickup_image(which):
    state=pickup.public()
    if which not in ('before','after') or state.get('phase')!='awaiting_visual':
        return jsonify(ok=False,error='No pending pickup image'),404
    path=state[which]['image']
    response=send_from_directory(os.path.dirname(path),os.path.basename(path))
    response.headers['Cache-Control']='no-store';return response

@app.post("/target")
def set_target():
    b = _body()
    try:
        runner.target = {
            "x": float(b["x"]), "y": float(b["y"]), "z": float(b["z"]),
            "rz": float(b["rz"]),
            "z_calibrated": float(b.get("z_calibrated", b["z"])),
            "config": b.get("config", "manual"),
            "found_at": time.strftime("%H:%M:%S"),
        }
        return jsonify({"ok": True, "target": runner.target})
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad target: {ex}"})


def _target_from(b: dict) -> dict | None:
    """Target sent by the UI (possibly operator-edited), else the stored one."""
    if all(k in b for k in ("x", "y", "z", "rz")):
        try:
            tgt = {"x": float(b["x"]), "y": float(b["y"]), "z": float(b["z"]),
                   "rz": float(b["rz"]),
                   "z_calibrated": float(b.get("z_calibrated", b["z"]))}
            runner.target = {**(runner.target or {}), **tgt}
            return tgt
        except ValueError:
            return None
    return runner.target


if __name__ == "__main__":
    print("S4 Operator Console -> http://127.0.0.1:5002")
    print("Reminders: only ONE robot TCP client (stop MCP/Bioyond Works), "
          "only ONE GigE owner (close MVS live view).")
    app.run(host="127.0.0.1", port=5002, threaded=True)
