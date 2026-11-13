"""S4 Operator Console — human-in-the-loop control panel.

Live eye-in-hand (GigE) camera view + every robot capability as a button:
state control, jog, gripper, and the vision pipeline broken into operator-
triggered stages (Find disk -> Align -> Descend -> Grip -> Lift), each of
which reports back and waits for the human's next decision.

Run: .venv-realsense/Scripts/python.exe -B operator_ui/app.py
Legacy py launches redirect to that same validated environment.

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

# Lacry's local chat now uses ChatGPT-authenticated Codex and MCP by default.
# An explicit legacy override is required to allow Anthropic API traffic.
os.environ.setdefault('LACRY_LLM_PROVIDER', 'codex_mcp')
if os.environ['LACRY_LLM_PROVIDER'] not in ('codex_mcp', 'anthropic'):
    raise RuntimeError('Choose LACRY_LLM_PROVIDER=codex_mcp or explicitly select legacy anthropic mode.')

from vision_runtime import bootstrap, verify as verify_vision_runtime
VISION_RUNTIME = bootstrap() if __name__ == '__main__' else verify_vision_runtime()

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

@app.get('/developer/api/vision/runtime')
def vision_runtime_status():
    return jsonify(VISION_RUNTIME)

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
app.extensions['developer_diagnostics'] = developer_diagnostics
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
    from calibration_e2 import verify
    verify(service, run, correct=True)
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
from pickup_holder import PickupHolder
ik_home_connection = IKHomeConnection(home_return)
from guarded_home_recovery import GuardedHomeRecovery
guarded_home_recovery = GuardedHomeRecovery(ik_home_connection)
from plate48_workflow import Plate48Teaching, Plate48Pickup
plate48_teaching = Plate48Teaching(lambda:svc,lambda:runner,lambda:cam,get_robot_params,
    plate_teaching._prepare,home_return,lambda:(plate_teaching.invalidate(),position_grip.invalidate()),band_floor)
pickup_home = PickupHolder(home_return,os.path.join(HERE,'demonstrations','pickup_holder'))
classic_pickup = Plate48Pickup(researcher_teaching, plate48_teaching, researcher_descent,
    position_grip, lambda: svc, lambda: runner, transport=pickup_home)
lacry = LacryAgent(lacry_backend, plate_agent.client, lambda: runner,
    memory=lacry_memory,
    # Same controller bring-up the researcher console ran for every action,
    # here run once a confirmed plan starts, with the step disclosed on the
    # confirmation card.
    prepare=plate_teaching._prepare, home_return=home_return,
    classic_pickup=classic_pickup, reviewed_home=ik_home_connection)
if os.environ['LACRY_LLM_PROVIDER'] == 'codex_mcp':
    from lacry_codex import CodexChat
    lacry.codex_chat = CodexChat(lacry)
register_researcher(app, lambda: dict(
    robot=svc.status(), camera=cam.info(),
    sequence=dict(active=runner.active or getattr(runner, 'reserved', False))), researcher_teaching, draggo, plate_teaching, imitation, home_return, hand_claw,
    routine_check=lambda saved: check_routine(saved, get_robot_params(), svc.envelope, svc.envelope_enabled),
    pickup_planner=pickup_planner,recorded_return=recorded_return,latest_hamilton=latest_hamilton,descent=researcher_descent,grip=position_grip,
    lacry=lacry)

@app.get('/developer/api/lacry/model')
def lacry_model_status():
    from lacry_model import request_options
    if lacry.codex_chat:
        return jsonify(ok=True, configured=True, **lacry.codex_chat.public(),
                       image_analysis_model='Codex via MCP camera image; legacy API analysis disabled')
    return jsonify(ok=True, configured=lacry.credentials.ready(),
                   **request_options(lacry.model,lacry.max_tokens),
                   image_analysis_model=plate_agent.client.model)


CAL_PATH = os.path.join(os.path.dirname(HERE), "grab_skill",
                        "calibration.json")

register_developer_diagnostics(app, developer_diagnostics, lambda: runner,
                               lambda: lacry.client, lambda: lacry.credentials)


@app.post('/developer/api/dsl/devin/home-check')
def developer_home_check():
    # Observation only: use the same Home preflight as the researcher button.
    from devin_review import capture_home_preflight, local_developer_request
    if not local_developer_request():
        return jsonify(ok=False, error='Use the local developer console.'), 403
    return jsonify(capture_home_preflight(developer_diagnostics, svc, home_return,
                                          draggo, get_robot_params))


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
from lacry_mcp_api import register as register_lacry_mcp
register_lacry_mcp(app, lacry, _dispatch_lock)


@app.before_request
def command_ownership():
    if request.method != "POST":
        return None
    if request.path.startswith('/researcher/api/lacry/mcp/'):
        return None  # Authenticated MCP handlers share _dispatch_lock; Stop stays available.
    if request.path == '/researcher/api/plate-transfer/stop':
        return None  # Exact-plan cancellation must remain available during motion.
    if request.path in ('/researcher/api/plate-transfer/plan', '/researcher/api/plate-transfer/start'):
        if not _dispatch_lock.acquire(blocking=False):
            return jsonify(ok=False, message='Another control is busy; no transfer was dispatched.'), 409
        request.environ['bioyond.dispatch_locked'] = True
        if runner.active or getattr(runner, 'reserved', False):
            return jsonify(ok=False, message='A lab task owns the runner; no transfer was dispatched.'), 409
        return None  # Preserve receipt/calibration state; the composition validates its own plan.
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
                        '/researcher/api/lacry/cancel', '/researcher/api/lacry/chat',
                        '/researcher/api/lacry/question/answer'):
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


@app.post('/seq/calibrate_48well')
def calibrate_48well_route():
    refusal = _refuse_if_sequencing()
    if refusal is not None:
        return refusal
    body = _body()
    if any(body.get(k) is not True for k in ('confirm','cell_clear','empty_gripper','plate_unchanged')):
        return jsonify(ok=False,error='Confirm the empty gripper, unchanged 48-well setup and clear observation route.'),400
    if recorder._run:
        return jsonify(ok=False,error='Stop torque recording before 48-well calibration.'),409
    try:
        return jsonify(plate48_teaching.start('Calibrate',dict(ready=True)))
    except (TeachingError, TransferError) as error:
        return jsonify(ok=False,error=str(error)),409


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


@app.route('/developer/api/home/manual-recovery', methods=['GET', 'POST'])
def manual_home_recovery_route():
    from home_recovery import acknowledge
    from researcher_teaching import TeachingError
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify(ok=False, error='Manual recovery review is local-only.'), 403
    try:
        if request.method == 'GET':
            return jsonify(ok=True, attempts=ik_home_connection.unresolved_attempts())
        return jsonify(acknowledge(ik_home_connection, _body()))
    except TeachingError as error:
        return jsonify(ok=False, error=str(error)), 400


@app.post('/developer/api/home/recovery/<action>')
def guarded_home_recovery_route(action):
    from researcher_teaching import TeachingError
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify(ok=False, error='Recovery review is local-only.'), 403
    try:
        if action == 'preview':
            return jsonify(guarded_home_recovery.preview())
        if action == 'confirm':
            return jsonify(guarded_home_recovery.confirm(_body()))
        return jsonify(ok=False, error='Unknown recovery action.'), 404
    except (TeachingError, TransferError) as error:
        return jsonify(ok=False, error=str(error)), 400


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


@app.post('/developer/api/hamilton-short-side-trial')
def hamilton_short_side_trial():
    from hamilton_short_side_trial import review, execute
    body=_body();direction=body.get('direction')
    if direction not in ('forward','reverse') or body!={'direction':direction,'ready':True,'empty_gripper':True,'path_clear':True}:
        return jsonify(ok=False,error='Confirm the empty-gripper Hamilton trial and clear path.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();approved=review(svc,cfg,direction)
        return jsonify(runner.start('hamilton_short_side_trial',execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/short-side-full-trial01')
def short_side_full_trial01():
    from short_side_full_trial import review,execute
    body=_body();phase=body.get('phase')
    if phase not in ('approach','hamilton') or body!={'phase':phase,'ready':True,'setup_confirmed':True,'path_clear':True}:
        return jsonify(ok=False,error='Confirm the short-side pickup/transfer setup and path.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();approved=review(svc,cfg,phase)
        return jsonify(runner.start('short_side_full_trial01',execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/short-side-full-trial02')
def short_side_full_trial02():
    from short_side_full_trial import review,execute
    body=_body();phase=body.get('phase')
    if phase not in ('approach','hamilton') or body!={'phase':phase,'ready':True,'setup_confirmed':True,'path_clear':True}:
        return jsonify(ok=False,error='Confirm pickup and direct Hamilton trial via the new turning pose.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();approved=review(svc,cfg,phase,'02')
        return jsonify(runner.start('short_side_full_trial02',execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/home-hamilton-exchange/preview')
@app.post('/developer/api/home-hamilton-exchange/start')
def home_hamilton_exchange():
    from home_hamilton_exchange import plan,execute
    body=_body()
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body) not in ({'calibration_record'},{'calibration_record','delivery_only'}):raise ValueError('Provide the fresh calibration record.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['calibration_record'],body.get('delivery_only',False)))
        if set(body)!={'plan','ready','path_clear','setup_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirm the HOME rotation, Hamilton path and holder return are clear.')
        return jsonify(runner.start('home_hamilton_exchange',execute,svc,cfg,body['plan']))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/home-hamilton-exchange/restore-original')
def home_hamilton_restore_original():
    from home_hamilton_exchange import restore_original
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    if _body()!={'ready':True,'empty_gripper':True,'holder_clear':True}:
        return jsonify(ok=False,error='Confirm released plate and clear holder rotation at IDLE.'),400
    return jsonify(runner.start('home_hamilton_restore_original',restore_original,svc))


@app.post('/developer/api/home-squid-transfer/preview')
@app.post('/developer/api/home-squid-transfer/start')
def home_squid_transfer_route():
    from home_squid_transfer import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'source'}:raise ValueError('Provide completed HOME receipt.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['source']))
        if set(body)!={'plan','ready','setup_confirmed','path_clear'} or any(body[k] is not True for k in ('ready','setup_confirmed','path_clear')):
            raise ValueError('Confirm released plate, clear holder rotation and new HOME/Squid route.')
        return jsonify(runner.start('home_squid_transfer',execute,svc,cfg,body['plan'],position_grip))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/home-squid-return/preview')
@app.post('/developer/api/home-squid-return/start')
def home_squid_return_route():
    from home_squid_transfer import plan_return,execute_return
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'source','phase'}:raise ValueError('Provide predecessor receipt and return phase.')
            return jsonify(ok=True,plan=plan_return(svc,cfg,body['source'],body['phase']))
        if set(body)!={'plan','ready','setup_confirmed','path_clear'} or any(body[k] is not True for k in ('ready','setup_confirmed','path_clear')):
            raise ValueError('Confirm held plate and route; release requires supported HOME seating.')
        return jsonify(runner.start('home_squid_return',execute_return,svc,cfg,body['plan']))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/home-squid-handling/preview')
@app.post('/developer/api/home-squid-handling/start')
def home_squid_handling_route():
    from home_squid_handling import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'source','phase'}:raise ValueError('Provide fresh source receipt and handling phase.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['source'],body['phase']))
        if set(body)!={'plan','ready','setup_confirmed','path_clear'} or any(body[k] is not True for k in ('ready','setup_confirmed','path_clear')):
            raise ValueError('Confirm supported Squid release, unchanged holder and clear empty/loaded routes.')
        return jsonify(runner.start('home_squid_handling',execute,svc,cfg,body['plan']))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/hamilton-holder-dropoff/preview')
@app.post('/developer/api/hamilton-holder-dropoff/start')
def hamilton_holder_dropoff():
    from hamilton_holder_dropoff import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'phase','source'}:raise ValueError('Provide phase and completed source receipt.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['phase'],body['source']))
        if set(body)!={'plan','ready','setup_confirmed','path_clear'} or any(body[k] is not True for k in ('ready','setup_confirmed','path_clear')):
            raise ValueError('Confirm setup and route; release requires supported plate, return requires jaws clear.')
        return jsonify(runner.start('hamilton_holder_dropoff',execute,svc,cfg,body['plan']))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/short-side-full-trial04')
@app.post('/developer/api/short-side-full-trial03')
def short_side_full_trial03():
    from short_side_full_trial import review,execute
    body=_body();phase=body.get('phase')
    attempt=body.get('attempt','')
    revision='04' if request.path.endswith('trial04') else '03'
    expected={'phase':phase,'ready':True,'setup_confirmed':True,'path_clear':True}
    if attempt:expected['attempt']=attempt
    if phase not in ('approach','hamilton','departure') or (phase=='departure' and revision!='04') or attempt not in ('','retry01','retry02','retry03') or (revision=='04' and attempt) or body!=expected:
        return jsonify(ok=False,error='Confirm the new raised turn, overhead crossing and two-speed vertical descent.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();approved=review(svc,cfg,phase,revision,attempt)
        return jsonify(runner.start('short_side_full_trial'+revision,execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/short-side-full-trial04/restore-holder')
@app.post('/developer/api/short-side-full-trial03/retry03/restore-holder')
@app.post('/developer/api/short-side-full-trial02/restore-holder')
def short_side_full_trial02_holder():
    from short_side_holder_restore import review,execute
    if _body()!={'ready':True,'empty_gripper':True,'holder_clear':True}:
        return jsonify(ok=False,error='Confirm empty jaws and clear small holder correction.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        profile='full_sequence03_retry03' if request.path.endswith('/retry03/restore-holder') else 'full_sequence02'
        if request.path.endswith('trial04/restore-holder'):profile='full_sequence04'
        approved=review(svc,profile)
        return jsonify(runner.start('short_side_full_trial02_holder',execute,svc,approved))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/holder/alignment-trial')
def short_side_alignment_trial():
    from short_side_alignment_trial import review, execute
    body=_body()
    candidate=body.get('candidate')
    if candidate not in ('direct','clearance','smooth_direct','smooth_repeat01','corrected02') or body!={'candidate':candidate,'ready':True,'empty_gripper':True,'path_clear':True}:
        return jsonify(ok=False,error='Confirm the supervised open-jaw route and empty gripper.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();approved=review(svc,cfg,candidate)
        return jsonify(runner.start('short_side_alignment_trial',execute,svc,cfg,approved))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/holder/restore-taught-angle')
def restore_taught_holder_angle():
    from short_side_holder_restore import review,execute
    if _body()!={'ready':True,'empty_gripper':True,'holder_clear':True}:
        return jsonify(ok=False,error='Confirm empty jaws and clear holder adjustment.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        approved=review(svc)
        return jsonify(runner.start('restore_taught_holder_angle',execute,svc,approved))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/holder/direction-probe')
@app.post('/developer/api/holder/complete-quarter-turn')
@app.post('/developer/api/holder/return-original')
@app.post('/developer/api/holder/fast-quarter-turn')
@app.post('/developer/api/holder/restore-test-start')
def holder_direction_probe():
    from holder_rotation_trial import direction_probe, snapshot, quarter_turn_target, verified_return, ROOT
    quarter = request.path.endswith('/complete-quarter-turn')
    returning = request.path.endswith('/return-original')
    fast = request.path.endswith('/fast-quarter-turn')
    restore_test = request.path.endswith('/restore-test-start')
    required = {'ready': True, 'empty_gripper': True, 'holder_clear': True}
    if quarter or returning or fast or restore_test:
        required['positive_e2_confirmed_ccw'] = True
    if fast:
        required['plate_retained'] = True
    if _body() != required:
        return jsonify(ok=False, error='Confirm empty jaws and the supervised clear holder sweep.'), 400
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    try:
        expected = None
        if quarter or returning or fast or restore_test:
            expected, _ = quarter_turn_target(json.loads((ROOT/'direction_probe.json').read_text()), True)
        if returning or fast:
            prior = verified_return()[1] if fast else json.loads((ROOT/'quarter_turn.json').read_text())
            allowed = ('original_restored','original_restored_by_readback','fast_start_restored') if fast else ('quarter_turn_completed',)
            if prior.get('status') not in allowed:
                raise ValueError('Previous holder motion has no verified completion')
            expected = prior['after']['native']['external_axes']['E2']
        if restore_test:
            expected=json.loads((ROOT/'fast137_startup.json').read_text())['after_native']['external_axes']['E2']
        snapshot(svc, expected)
        if quarter or returning or fast or restore_test:
            name = 'holder_restore_test_start' if restore_test else 'holder_return_original' if returning else 'holder_fast_quarter_turn' if fast else 'holder_quarter_turn'
            return jsonify(runner.start(name, lambda run: direction_probe(run, svc, quarter=quarter, confirmed_ccw=True, return_original=returning, fast=fast, restore_test=restore_test)))
        return jsonify(runner.start('holder_direction_probe', direction_probe, svc))
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 409


@app.post('/developer/api/hamilton-stopped-return/preview')
@app.post('/developer/api/hamilton-stopped-return/start')
def hamilton_stopped_return():
    from hamilton_stopped_return import review,execute
    if _body()!={'ready':True,'plate_secure':True,'path_clear':True}:
        return jsonify(ok=False,error='Confirm secure plate and clear Hamilton recovery route.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg)
        if request.path.endswith('/preview'):return jsonify(ok=True,plan=plan)
        return jsonify(runner.start('hamilton_stopped_return',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/hamilton-release/preview')
@app.post('/developer/api/hamilton-release/start')
def hamilton_release_start():
    from hamilton_release_20261108 import review,execute
    from hamilton_reteach_trial import SHA
    body=_body()
    if (body.get('ready') is not True or body.get('supported_and_clear') is not True or body.get('candidate_sha256')!=SHA
            or set(body)-{'ready','supported_and_clear','candidate_sha256','trial_id','forward_trial_id','operation'}):
        return jsonify(ok=False,error='Confirm supported plate, clear claws and this exact Hamilton endpoint.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg,body.get('trial_id'),body.get('forward_trial_id'),body.get('operation','release'))
        if request.path.endswith('/preview'):return jsonify(ok=True,plan=plan)
        return jsonify(runner.start('hamilton_release_empty_home',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/squid-queue/preview')
@app.post('/developer/api/squid-queue/start')
def squid_single_queue_start():
    from squid_single_queue import review,execute,CURRENT_SHA
    body=_body()
    if (set(body)!={'ready','direction','trial_id','candidate_sha256'} or body.get('ready') is not True
            or body.get('candidate_sha256')!=CURRENT_SHA or body.get('direction') not in ('forward','reverse')):
        return jsonify(ok=False,error='Confirm this exact Squid route, direction and fresh trial ID.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg,body['direction'],body['trial_id'])
        if request.path.endswith('/preview'):return jsonify(ok=True,plan=plan)
        return jsonify(runner.start('squid_single_queue',execute,svc,cfg,plan))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/hamilton-reteach/start')
def hamilton_reteach_start():
    from hamilton_reteach_trial import SHA,review,execute
    body=_body();direction=body.get('direction','forward')
    if (direction not in ('forward','reverse') or body.get('ready') is not True
            or body.get('candidate_sha256')!=SHA or set(body)-{'ready','candidate_sha256','direction','trial_id','forward_trial_id'}):
        return jsonify(ok=False,error='Confirm the exact revised Hamilton trial and clear supervised route.'),400
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg,reverse=direction=='reverse',
            trial_id=body.get('trial_id'),forward_trial_id=body.get('forward_trial_id'))
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


@app.post('/developer/api/squid-48well-approach/start')
def squid_48well_approach_start():
    from squid_48well_approach import SHA, review, execute
    if _body() != dict(ready=True, plate_held=True, approach_only=True, candidate_sha256=SHA):
        return jsonify(ok=False,error='Confirm held plate, clear supervised route, and approach only.'),400
    refusal = _refuse_if_sequencing()
    if refusal is not None:
        return refusal
    try:
        cfg=get_robot_params();plan=review(svc,cfg)
        return jsonify(runner.start('squid_48well_approach',execute,svc,cfg,plan))
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


@app.post('/developer/api/cellvis24-short-side/preview')
@app.post('/developer/api/cellvis24-short-side/start')
def cellvis24_short_side_trial():
    from cellvis24_station_trial import plan, execute
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    body = _body()
    try:
        cfg = get_robot_params()
        if request.path.endswith('/preview'):
            if body:
                raise ValueError('This Cellvis trial takes no arbitrary targets.')
            return jsonify(ok=True, plan=plan(svc, cfg))
        if set(body) != {'plan', 'ready', 'path_clear', 'setup_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirmed Cellvis setup and clear holder/arm sweep required.')
        return jsonify(runner.start('cellvis24_short_side', execute, svc, cfg, body['plan']))
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 409


@app.post('/developer/api/cellvis24-hamilton/preview')
@app.post('/developer/api/cellvis24-hamilton/start')
def cellvis24_hamilton_delivery():
    from cellvis24_hamilton_route import plan, execute
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    body = _body()
    try:
        cfg = get_robot_params()
        if request.path.endswith('/preview'):
            if body:
                raise ValueError('This Cellvis route takes no arbitrary targets.')
            return jsonify(ok=True, plan=plan(svc, cfg))
        if set(body) != {'plan','ready','path_clear','setup_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirmed Cellvis grip, Hamilton setup and route clearance required.')
        return jsonify(runner.start('cellvis24_hamilton', execute, svc, cfg, body['plan']))
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 409


@app.post('/developer/api/cellvis24-handling/preview')
@app.post('/developer/api/cellvis24-handling/start')
def cellvis24_station_handling():
    from cellvis24_station_handling import plan, execute
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    body = _body()
    try:
        cfg = get_robot_params()
        if request.path.endswith('/preview'):
            if set(body) != {'phase'}:
                raise ValueError('Select the Cellvis handling phase.')
            return jsonify(ok=True, plan=plan(svc, cfg, body['phase']))
        if set(body) != {'plan','ready','path_clear','setup_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirmed Cellvis handling setup and clear route required.')
        return jsonify(runner.start('cellvis24_handling', execute, svc, cfg, body['plan']))
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 409


@app.post('/developer/api/cellvis24-squid/preview')
@app.post('/developer/api/cellvis24-squid/start')
def cellvis24_squid_handling():
    from cellvis24_squid_route import plan, execute
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    body = _body()
    try:
        cfg = get_robot_params()
        if request.path.endswith('/preview'):
            if set(body) != {'phase'}:
                raise ValueError('Select the Cellvis Squid phase.')
            return jsonify(ok=True, plan=plan(svc, cfg, body['phase']))
        if set(body) != {'plan','ready','path_clear','setup_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirmed Cellvis handling setup and clear route required.')
        return jsonify(runner.start('cellvis24_squid', execute, svc, cfg, body['plan']))
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 409


@app.get('/developer/api/cellvis24-workflow/capabilities')
def cellvis24_workflow_capabilities():
    from cellvis24_recorded_hamilton_route import PLAN,reference,plan_path
    import hashlib
    reference()
    return jsonify(ok=True,recorded_hamilton_delivery=True,
                   route_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                   recorded_route_variants={v:hashlib.sha256(plan_path(v).read_bytes()).hexdigest() for v in ('recorded','smooth3','blend3','opposite3')})


@app.post('/developer/api/cellvis24-workflow/blend-ready')
def cellvis24_blend_ready():
    """Nonmoving capability handshake before calibration; never starts Lua."""
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    from hamilton_transit_blend import require_capability
    try:
        body=_body()
        if set(body)-{'variant'} or body.get('variant','blend3') not in ('blend3','opposite3'):
            raise ValueError('Only a known blend variant is accepted; no motion parameters.')
        refusal=svc._preflight()
        if refusal:raise ValueError(refusal)
        result=svc._locked(lambda:require_capability(svc,body.get('variant','blend3')))
        return jsonify(result),200 if result.get('ok') else 409
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/home-clearance-recovery/preview')
@app.post('/developer/api/home-clearance-recovery/start')
def cellvis_home_clearance_recovery():
    from home_clearance_recovery import preview, execute
    refusal = _refuse_if_sequencing()
    if refusal:
        return refusal
    body = _body()
    try:
        cfg = get_robot_params()
        if request.path.endswith('/preview'):
            if body:
                raise ValueError('HOME recovery preview accepts no arbitrary positions or routes.')
            return jsonify(ok=True, plan=preview(svc, cfg))
        required = {'plan', 'ready', 'empty_jaws', 'plate_seated', 'path_clear'}
        if set(body) != required or any(body[k] is not True for k in required - {'plan'}):
            raise ValueError('Confirm empty jaws, seated Cellvis plate and clear HOME holder/connector.')
        return jsonify(runner.start('home_clearance_recovery', execute, svc, cfg, body['plan'], True, True))
    except Exception as error:
        return jsonify(ok=False, error=str(error)), 409


@app.post('/developer/api/cellvis24-workflow/preview')
@app.post('/developer/api/cellvis24-workflow/start')
def cellvis24_reusable_workflow():
    from cellvis24_workflow import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if not {'stations','cycles','source'}<=set(body) or set(body)-{'stations','cycles','source','full_calibration','projected_trial','held_hamilton_roundtrip','direct_hamilton','taught_hamilton_delivery','recorded_hamilton_delivery','recorded_hamilton_variant'}:raise ValueError('Select stations, cycles, source receipt and optional calibration/held-Hamilton mode.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['stations'],body['cycles'],body['source'],body.get('full_calibration',False),body.get('projected_trial',False),body.get('held_hamilton_roundtrip',False),body.get('direct_hamilton',False),body.get('taught_hamilton_delivery',False),body.get('recorded_hamilton_delivery',False),body.get('recorded_hamilton_variant','recorded')))
        required={'plan','ready','path_clear','setup_confirmed'}
        if body.get('plan',{}).get('recorded_hamilton_delivery') or body.get('plan',{}).get('recorded_hamilton_variant')=='opposite3':
            required.add('recorded_clearance_confirmed')
            if body.get('recorded_clearance_confirmed') is not True:raise ValueError('Confirm the recorded-height route and its HOME/final placement connectors are clear.')
        if body.get('plan',{}).get('taught_hamilton_delivery'):
            required.add('taught_clearance_confirmed')
            if body.get('taught_clearance_confirmed') is not True:raise ValueError('Confirm the combined HOME-to-taught-turn-to-Hamilton sweep is clear.')
        if body.get('plan',{}).get('direct_hamilton'):
            required.add('direct_clearance_confirmed')
            if body.get('direct_clearance_confirmed') is not True:raise ValueError('Review the new HOME wrist sweep and direct diagonal rack crossing first.')
        if set(body)!=required or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirmed Cellvis setup and clear route required.')
        return jsonify(runner.start('cellvis24_workflow',execute,svc,cfg,body['plan'],cam))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/cellvis24-hamilton-continuation/preview')
@app.post('/developer/api/cellvis24-hamilton-continuation/start')
def cellvis24_hamilton_continuation():
    from cellvis24_hamilton_continuation import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'source','phase'}:raise ValueError('Source receipt and continuation phase required.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['source'],body['phase']))
        if set(body)!={'plan','ready','path_clear','setup_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','setup_confirmed')):
            raise ValueError('Confirmed loaded return and HOME/Squid setup required.')
        return jsonify(runner.start('cellvis24_continuation',execute,svc,cfg,body['plan']))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/cellvis24-adjustment/prepare')
@app.post('/developer/api/cellvis24-adjustment/trial')
def cellvis24_adjustment_trial():
    # Operator rejected the adapted alignment. Preserve its evidence, but do
    # not allow an old browser/request to dispatch it again.
    return jsonify(ok=False,error='Experimental Cellvis adjustment retired. Use the accepted Cellvis full-calibration sequence.'),410


@app.post('/developer/api/scanner-empty/preview')
@app.post('/developer/api/scanner-empty/start')
def scanner_empty_trial():
    from scanner_empty_route import plan, execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Scanner preview accepts no arbitrary route parameters.')
            return jsonify(ok=True,plan=plan(svc,cfg))
        if set(body)!={'plan','ready','path_clear','empty_gripper','workspace_change_confirmed'} or any(body[k] is not True for k in ('ready','path_clear','empty_gripper','workspace_change_confirmed')):
            raise ValueError('Confirm supervised empty-arm scanner route and temporary X minimum80.')
        return jsonify(runner.start('scanner_empty_trial',execute,svc,cfg,body['plan']))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/cellvis-scanner-return/review-home')
def cellvis_scanner_review_home():
    from cellvis24_scanner_return import review_recovered_home
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        if set(body)!={'recovery','plate_seated','hands_clear','estop_supervised'} or any(body[k] is not True for k in ('plate_seated','hands_clear','estop_supervised')):
            raise ValueError('Confirm plate reseated flat in HOME, hands clear and E-stop supervised.')
        return jsonify(review_recovered_home(svc,get_robot_params(),body['recovery'],True))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/cellvis-scanner-return/preview')
@app.post('/developer/api/cellvis-scanner-return/start')
def cellvis_scanner_return():
    from cellvis24_scanner_return import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'trial_id','phase'}:raise ValueError('Supply trial_id and return_home/release_home phase.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['trial_id'],body['phase']))
        if set(body)!={'plan','ready','path_clear','plate_supported'} or body['ready'] is not True or body['path_clear'] is not True:
            raise ValueError('Confirm secure plate, clear loaded return and supervised E-stop.')
        if body['plan']['phase']=='release_home' and body['plate_supported'] is not True:
            raise ValueError('Confirm plate supported in HOME and jaws clear before release.')
        return jsonify(runner.start('cellvis_scanner_return',execute,svc,cfg,body['plan']))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/cellvis-scanner/preview')
@app.post('/developer/api/cellvis-scanner/start')
def cellvis_scanner_transfer():
    from cellvis24_scanner_route import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'trial_id'}:raise ValueError('Supply the completed Cellvis trial ID.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['trial_id']))
        confirmations=('plate_secure','loaded_path_clear','estop_supervised')
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm secure proof lift, cleared loaded scanner route and E-stop supervision.')
        return jsonify(runner.start('cellvis_scanner_transfer',execute,svc,cfg,body['plan']))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


_scanner_plate_workflow = None

@app.get('/developer/api/scanner-plate/status')
@app.post('/developer/api/scanner-plate/preview')
@app.post('/developer/api/scanner-plate/start')
def scanner_plate_trial():
    global _scanner_plate_workflow
    from scanner_plate_workflow import ScannerPlateWorkflow, ScannerProofLift
    try:
        if _scanner_plate_workflow is None:
            transport=ScannerProofLift(home_return,os.path.join(HERE,'demonstrations','scanner_proof_lift'))
            flow=Plate48Pickup(researcher_teaching,plate48_teaching,researcher_descent,
                position_grip,lambda:svc,lambda:runner,transport=transport)
            _scanner_plate_workflow=ScannerPlateWorkflow(flow,svc,runner,get_robot_params)
        if request.method=='GET':return jsonify(ok=True,**_scanner_plate_workflow.public())
        refusal=_refuse_if_sequencing()
        if refusal:return refusal
        body=_body()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Scanner pickup preview accepts no arbitrary targets.')
            return jsonify(ok=True,plan=_scanner_plate_workflow.preview())
        confirmations=('ready','path_clear','empty_gripper','plate_unchanged','loaded_path_clear','workspace_change_confirmed')
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm unchanged 48-well HOME setup, empty starting arm, loaded clearance, E-stop supervision and temporary X minimum80.')
        return jsonify(_scanner_plate_workflow.start(body['plan']))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/hamilton-empty-clearance/preview')
@app.post('/developer/api/hamilton-empty-clearance/start')
def hamilton_empty_clearance_trial():
    from hamilton_rack_clearance import plan, execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)-{'direction'}:raise ValueError('Preview accepts only a route direction.')
            return jsonify(ok=True,plan=plan(svc,cfg,body.get('direction','roundtrip')))
        confirmations=('empty_gripper','path_clear','door_open','estop_supervised','arm_released')
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm empty jaws, open Hamilton access, clear route, released arm and supervised E-stop.')
        return jsonify(runner.start('hamilton_empty_clearance',execute,svc,cfg,body['plan']))
    except Exception as error:
        return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/hotel-home-pickup/preview')
@app.post('/developer/api/hotel-home-pickup/start')
def hotel_home_pickup():
    from hotel_home_pickup import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Saved 48-well pickup only.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'plate_setup_confirmed','empty_gripper','route_and_holder_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm HOME pickup setup, empty jaws, route/holder clearance and supervision.')
        return jsonify(runner.start('hotel_home_pickup',execute,svc,cfg,body['plan'],position_grip))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot1-retrieval/preview')
@app.post('/developer/api/hotel-slot1-retrieval/start')
def hotel_slot1_retrieval():
    from hotel_slot1_retrieval import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Exact accepted slot1 retrieval only.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'plate_in_slot1','home_empty','lift5_and_route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm slot1 plate, empty HOME, five-millimeter lift and route clearance, supervision.')
        return jsonify(runner.start('hotel_slot1_retrieval',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot2-taught/preview')
@app.post('/developer/api/hotel-slot2-taught/start')
@app.post('/developer/api/hotel-slot3-taught/preview')
@app.post('/developer/api/hotel-slot3-taught/start')
def hotel_slot2_taught():
    from hotel_slot2_trial import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    slot=3 if '/hotel-slot3-taught/' in request.path else 2
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError(f'Exact slot{slot} approach only.')
            return jsonify(ok=True,plan=preview(svc,cfg,slot))
        confirmations={'plate_secure',f'slot{slot}_empty','loaded_route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError(f'Confirm held plate, empty slot{slot}, loaded route clearance and supervision.')
        if body['plan']['geometry']['slot']!=slot:raise ValueError('Preview slot differs from requested slot.')
        return jsonify(runner.start(f'hotel_slot{slot}_taught',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot2-handling/preview')
@app.post('/developer/api/hotel-slot2-handling/start')
@app.post('/developer/api/hotel-slot3-handling/preview')
@app.post('/developer/api/hotel-slot3-handling/start')
def hotel_slot2_handling_route():
    slot=3 if '/hotel-slot3-handling/' in request.path else 2
    if slot==3:
        from hotel_slot3_handling import preview,execute
    else:
        from hotel_slot2_handling import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'action'}:raise ValueError('Specify release_return or retrieve.')
            return jsonify(ok=True,plan=preview(svc,cfg,body['action']))
        confirmations={'plate_setup_confirmed','route_and_lift_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm plate support/location, opening and horizontal retreat, 5mm lift clearance and supervision.')
        if body['plan']['geometry']['approach_geometry']['slot']!=slot:raise ValueError('Handling preview slot differs from request.')
        return jsonify(runner.start(f'hotel_slot{slot}_handling',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-home-teaching-pickup/preview')
@app.post('/developer/api/hotel-home-teaching-pickup/start')
def hotel_home_teaching_pickup():
    from hotel_slot1_delivery import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Accepted HOME pickup only.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'plate_in_home','empty_gripper','pickup_route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm plate in HOME, empty jaws, pickup/lift clearance and supervision.')
        def pickup(run):
            return execute(run,svc,cfg,body['plan'],position_grip,pickup_only=True)
        return jsonify(runner.start('hotel_home_teaching_pickup',pickup))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot1-delivery/preview')
@app.post('/developer/api/hotel-slot1-delivery/start')
def hotel_slot1_delivery():
    from hotel_slot1_delivery import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Exact taught slot1 delivery only.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'plate_in_home','slot1_empty','loaded_route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm plate in HOME, empty slot1, loaded route/release clearance and supervision.')
        return jsonify(runner.start('hotel_slot1_delivery',execute,svc,cfg,body['plan'],position_grip))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot1-lower-recovery/preview')
@app.post('/developer/api/hotel-slot1-lower-recovery/start')
def hotel_slot1_lower_recovery():
    from hotel_slot1_lower_recovery import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Recovery is pinned to the confirmed manual exit.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'empty_and_free','route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm empty free arm, exact route and supervision.')
        return jsonify(runner.start('hotel_slot1_lower_recovery',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot1-empty-recovery/preview')
@app.post('/developer/api/hotel-slot1-empty-recovery/start')
def hotel_slot1_empty_recovery():
    from hotel_slot1_empty_recovery import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Recovery is pinned to the confirmed manual exit.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'empty_and_free','route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm empty free arm, exact route and supervision.')
        return jsonify(runner.start('hotel_slot1_empty_recovery',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot2-recovery/preview')
@app.post('/developer/api/hotel-slot2-recovery/start')
def hotel_slot2_recovery():
    from hotel_slot2_recovery import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if body:raise ValueError('Recovery uses its pinned current-pose route only.')
            return jsonify(ok=True,plan=preview(svc,cfg))
        confirmations={'empty_and_free','route_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm empty free arm, exact recovery clearance and supervision.')
        return jsonify(runner.start('hotel_slot2_recovery',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot2-pickup/preview')
@app.post('/developer/api/hotel-slot2-pickup/start')
def hotel_slot2_pickup():
    from hotel_slot2_pickup import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)-{'phase','source'}:raise ValueError('Only slot2 phase/source accepted.')
            return jsonify(ok=True,plan=preview(svc,cfg,body.get('phase','pickup'),body.get('source')))
        confirmations={'plate_setup_confirmed','route_clear','estop_supervised'}
        if body.get('plan',{}).get('phase')=='return':confirmations.add('retention_confirmed')
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Slot2 plate, route and supervision confirmations required; return requires secure lift observation.')
        return jsonify(runner.start('hotel_slot2_pickup',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/hotel-slot1-trial/preview')
@app.post('/developer/api/hotel-slot1-trial/start')
def hotel_slot1_trial():
    from hotel_slot_trial import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)-{'direction'}:raise ValueError('Only Path A direction may be selected.')
            return jsonify(ok=True,plan=preview(svc,cfg,body.get('direction','forward')))
        confirmations={'empty_gripper','routes_clear','arm_released','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm empty jaws, clear HOME/slot1 routes, arm released and E-stop supervised.')
        return jsonify(runner.start('hotel_slot1_trial',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/cellvis-recovery-handoff/preview')
@app.post('/developer/api/cellvis-recovery-handoff/start')
def cellvis_recovery_handoff():
    from cellvis_recovery_handoff import preview,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body)!={'recovery','trial_id'}:raise ValueError('Supply completed recovery and accepted scanner geometry.')
            return jsonify(ok=True,plan=preview(svc,cfg,body['recovery'],body['trial_id']))
        confirmations={'plate_seated','empty_gripper','rotation_clear','estop_supervised'}
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm supported plate, empty open jaws, clear holder rotation and supervised E-stop.')
        return jsonify(runner.start('cellvis_recovery_handoff',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


@app.post('/developer/api/barcode-opposite-trial/preview')
@app.post('/developer/api/barcode-opposite-trial/start')
def barcode_opposite_trial():
    from barcode_opposite_side_trial import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body) not in ({'source'},{'source','target'}):raise ValueError('Provide the completed scanner HOME release receipt and optional inspected orientation.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['source'],body.get('target')))
        confirmations=('plate_seated','empty_gripper','rotation_and_approach_clear','estop_supervised')
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm supported plate, released jaws, clear half-turn/approach and supervised E-stop.')
        return jsonify(runner.start('barcode_opposite_trial',execute,svc,cfg,body['plan']))
    except Exception as error:return jsonify(ok=False,error=str(error)),409


@app.post('/developer/api/barcode-opposite-transport/preview')
@app.post('/developer/api/barcode-opposite-transport/start')
def barcode_opposite_transport():
    from barcode_opposite_transport import plan,execute
    refusal=_refuse_if_sequencing()
    if refusal:return refusal
    body=_body()
    try:
        cfg=get_robot_params()
        if request.path.endswith('/preview'):
            if set(body) not in ({'source','phase'},{'source','phase','scanner_z'}):raise ValueError('Provide pickup receipt, transport phase and optional reviewed scanner Z.')
            return jsonify(ok=True,plan=plan(svc,cfg,body['source'],body['phase'],body.get('scanner_z')))
        confirmations={'retention_confirmed','route_clear','estop_supervised'}
        if body.get('plan',{}).get('binding',{}).get('phase')=='release_restore':confirmations.add('plate_supported')
        if set(body)!={'plan',*confirmations} or any(body[k] is not True for k in confirmations):
            raise ValueError('Confirm secure plate, cleared scanner route and supervised E-stop.')
        return jsonify(runner.start('barcode_opposite_transport',execute,svc,cfg,body['plan']))
    except Exception as e:return jsonify(ok=False,error=str(e)),409


if __name__ == "__main__":
    print("S4 Operator Console -> http://127.0.0.1:5002")
    print("Reminders: only ONE robot TCP client (stop MCP/Bioyond Works), "
          "only ONE GigE owner (close MVS live view).")
    app.run(host="127.0.0.1", port=5002, threaded=True)
