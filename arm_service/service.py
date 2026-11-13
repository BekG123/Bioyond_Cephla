"""The arm service: plans of one leg, one run at a time, Stop, Clear errors, restart of the controller program.

A plan is made first (nothing moves): the leg, the arm's state now, and every move checked for reach, joint limits
and winding from the actual joints. A person starts it (POST start). The run then goes step by step; only one state
read separates two steps. Stop stops the controller program at once (the physical E-stop stays the real emergency
stop). Clear errors and the program restart are refused while a run is active.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from arm_service import ROOT, routes
from concurrent.futures import ThreadPoolExecutor

from arm_service.motion import (MotionError, arrived, close_on_plate, command_jaws, jaws, near, run_queue, settle,
                                squid_ready, state, upload_queue)

RUNS = ROOT / "arm_service" / "runs"
PLAN_MINUTES = 10  # a plan older than this is made again
STATUS_CACHE_S = 1.0
NAMES = {"load": "Hotel slot {slot} → microscope", "unload": "Microscope → hotel slot {slot}",
         "recover": "Empty arm back to the safe position"}
REQUIREMENTS = ["Someone is at the E-stop.", "The arm's path and the slot are clear."]


def _robot_service():
    from robot_service import RobotService
    from draggo import DragGo

    service = RobotService()
    service.draggo_guard = DragGo(lambda: service, routes.OPERATOR_UI / "demonstrations/draggo-active.json")
    return service


def _cfg():
    from sequences import get_robot_params

    return get_robot_params()


class Refused(RuntimeError):
    """The request was refused before anything was sent to the arm."""


class ArmService:
    def __init__(self, service=None, *, cfg=None, taught=None, squid_check=None, runs: Path = RUNS,
                 clock=time.time) -> None:
        self.service = service or _robot_service()
        self._cfg = cfg
        self._taught = taught  # tests give fixed routes; normally read again for each plan
        self._squid_check = squid_check or squid_ready
        self._runs = Path(runs)
        self._clock = clock
        self._lock = threading.RLock()
        self._plan: dict | None = None
        self._run: dict = dict(active=False)
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.plate: dict | None = None  # where this service last put the plate, and when
        self._status: tuple[float, dict] = (0.0, {})

    # --- reading ---

    def robot(self) -> dict:
        """The controller's state for the page, read at most once a second."""
        at, cached = self._status
        if time.monotonic() - at < STATUS_CACHE_S:
            return cached
        s = self.service.status()
        out = dict(connected=bool(s.get("connected")), errors=s.get("errors") or [], enabled=s.get("enabled"),
                   program=(s.get("program_state") or {}).get("state"), mode=(s.get("control_mode") or {}).get("mode"),
                   pose=s.get("pose_mm"), e1=(s.get("external_axes") or {}).get("E1"), message=s.get("error", ""))
        self._status = (time.monotonic(), out)
        return out

    def state(self) -> dict:
        robot = self.robot()
        pose, home = robot.get("pose"), self._home()
        at_home = bool(pose and home and all(abs(pose[k] - home[k]) <= 0.5 for k in ("X", "Y", "Z", "Rz")))
        with self._lock:
            return dict(robot=dict(robot, at_safe_position=at_home), plan=self.public_plan(self._plan),
                        run=dict(self._run), plate=self.plate, slots=list(routes.SLOTS))

    def _home(self) -> dict | None:
        if getattr(self, "_home_pose", None) is None:
            try:
                self._home_pose = routes.legs(self._taught)["home"] if self._taught else routes.taught()["home"]
            except Exception:  # noqa: BLE001  the page still shows the rest
                return None
        return self._home_pose

    # --- buttons that move nothing ---

    def connect(self) -> dict:
        if self.service.robot.connected:
            return dict(ok=True, message="The robot is connected.")
        from standalone_plate_transfer import assert_robot_available
        from robot_service import DEFAULT_IP, DEFAULT_PORT

        try:
            assert_robot_available(DEFAULT_IP, DEFAULT_PORT)
        except Exception as error:  # noqa: BLE001
            raise Refused(str(error)) from error
        result = self.service.connect()
        if not result.get("ok"):
            raise Refused(result.get("error") or "The robot did not connect.")
        self._status = (0.0, {})
        return dict(ok=True, message="The robot is connected.")

    def clear_errors(self) -> dict:
        self._require_idle("Clear errors")
        result = self.service.clear_errors(confirmed=True)  # the person pressed the button
        self._status = (0.0, {})
        if not result.get("ok"):
            raise Refused(result.get("error") or "The controller did not clear its errors.")
        left = result.get("errors_after") or []
        return dict(ok=not left, errors=left,
                    message="Errors cleared." if not left else "Some errors remain: check the arm and the E-stop.")

    def start_program(self) -> dict:
        """The controller program after a Stop. It closes the jaws fully, so it is refused while the gripper holds
        a plate (the console's own guard)."""
        self._require_idle("Restart")
        result = self.service.program("start")
        self._status = (0.0, {})
        if not result.get("ok"):
            raise Refused(result.get("error") or "The controller program did not start.")
        return dict(ok=True, message="The controller program runs.", notes=result.get("notes", []))

    def stop(self) -> dict:
        """Stop the controller program now, and the run with it. Sent also when no run is active."""
        self._cancel.set()
        result = self.service.program("stop")
        self._status = (0.0, {})
        with self._lock:
            if self._run.get("active"):
                self._run["stop_pressed_at"] = self._clock()
        if not result.get("ok"):
            raise RuntimeError(f"The controller did not confirm Stop ({result.get('error')}): use the E-stop.")
        return dict(ok=True, message="Stop sent: the controller program stops. Use the E-stop if the arm still moves.")

    # --- plans and runs ---

    def plan(self, direction: str, slot: int = 1) -> dict:
        """The plan of one leg. Nothing moves. A plan with blockers cannot start."""
        if direction not in NAMES:
            raise Refused("Choose load (slot to microscope) or unload (microscope to slot).")
        if direction == "recover":
            return self._plan_recovery()
        if type(slot) is not int or slot not in routes.SLOTS:
            raise Refused(f"Only slot {', '.join(map(str, routes.SLOTS))} is taught for this plate.")
        self._require_idle("A new plan")
        blockers: list[str] = []
        t = self._taught or routes.taught()
        legs = routes.legs(t)
        steps = [dict(s) for s in legs[direction]]
        cfg = self._cfg or _cfg()
        if cfg != t["delivery"]["cfg"]:
            blockers.append("The robot settings differ from the accepted routes.")
        if {k: list(v) for k, v in self.service.envelope.items()} != t["delivery"]["envelope"]:
            blockers.append("The safety box differs from the accepted routes.")
        pre: list[dict] = []
        try:
            s, n = state(self.service)
            near(s["pose_mm"], legs["home"], what="the safe position (HOME clearance)")
            e1 = n["external_axes"]["E1"]
            if abs(e1 - routes.EMPTY_E1) > 0.15:
                if e1 > routes.EMPTY_E1 or e1 < 3.0:  # open wider, or closed past any plate: the jaws are empty
                    pre.append(dict(kind="jaws", label=f"Set the empty jaws to {routes.EMPTY_E1:g} mm"))
                else:
                    blockers.append(f"The gripper is at {e1:.2f} mm: it may hold a plate. Check the arm.")
            q, pose = s["joints"], s["pose_mm"]
            for step in steps:
                if step["kind"] == "queue":
                    q = routes.check_queue(pose, q, step["points"], cfg, self.service.envelope)
                    step["expected"] = q
                    pose = step["points"][-1]
        except (MotionError, Exception) as error:  # noqa: BLE001  any check that refuses is a blocker
            blockers.append(str(error))
        if direction == "load" and self.plate and self.plate.get("at") == "Squid":
            blockers.append("This service put a plate at Squid: take it back first.")
        try:
            self._squid_check()
        except Exception as error:  # noqa: BLE001
            blockers.append(str(error))
        plan = dict(id=uuid.uuid4().hex, at=self._clock(), direction=direction, slot=slot,
                    summary=NAMES[direction].format(slot=slot), steps=pre + steps,
                    labels=[x["label"] for x in pre + steps], requirements=list(REQUIREMENTS),
                    blockers=blockers, executable=not blockers)
        with self._lock:
            self._plan = plan
        return self.public_plan(plan)

    def _plan_recovery(self) -> dict:
        """The empty arm stopped where it had just released the plate (in slot 1 or on the Squid seat), for example
        after a lost reply: the taught empty way back to the safe position from there. Nothing else is offered."""
        self._require_idle("A new plan")
        blockers: list[str] = []
        t = self._taught or routes.taught()
        cfg = self._cfg or _cfg()
        steps: list[dict] = []
        where = "an unknown place"
        try:
            s, n = state(self.service)
            e1 = n["external_axes"]["E1"]
            if abs(e1 - routes.EMPTY_E1) > 0.15:
                raise MotionError(f"The jaws are at {e1:.2f} mm, not open at {routes.EMPTY_E1:g} mm: the arm may "
                                  "hold the plate. Move it by hand control, not with this service.")
            for option in routes.recoveries(t):
                try:
                    near(s["pose_mm"], option["at"], tolerance_mm=0.5)
                except MotionError:
                    continue
                step = dict(option["step"])
                step["expected"] = routes.check_queue(s["pose_mm"], s["joints"], step["points"], cfg,
                                                      self.service.envelope)
                steps, where = [step], option["where"]
                break
            else:
                raise MotionError("The arm is not where a plate was just released (slot 1 or the Squid seat). "
                                  "It can be brought back only from there; otherwise use the robot's own controls.")
        except Exception as error:  # noqa: BLE001
            blockers.append(str(error))
        plan = dict(id=uuid.uuid4().hex, at=self._clock(), direction="recover", slot=None,
                    summary=f"{NAMES['recover']} (from {where})", steps=steps, labels=[x["label"] for x in steps],
                    requirements=list(REQUIREMENTS), blockers=blockers, executable=not blockers)
        with self._lock:
            self._plan = plan
        return self.public_plan(plan)

    @staticmethod
    def public_plan(plan: dict | None) -> dict | None:
        if plan is None:
            return None
        return dict(id=plan["id"], summary=plan["summary"], direction=plan["direction"], slot=plan["slot"],
                    steps=[dict(label=label) for label in plan["labels"]], requirements=plan["requirements"],
                    blockers=plan["blockers"], executable=plan["executable"])

    def cancel_plan(self, plan_id: str) -> dict:
        with self._lock:
            if not self._plan or self._plan["id"] != plan_id:
                raise Refused("No such plan waits.")
            self._plan = None
        return dict(ok=True)

    def start(self, plan_id: str) -> dict:
        """A person starts the plan that waits (someone is at the E-stop). The run goes on in its own thread."""
        with self._lock:
            plan = self._plan
            if not plan or plan["id"] != plan_id:
                raise Refused("This plan does not wait any more: make a new plan.")
            if not plan["executable"]:
                raise Refused("This plan cannot start: " + " ".join(plan["blockers"]))
            if self._clock() - plan["at"] > PLAN_MINUTES * 60:
                self._plan = None
                raise Refused("The plan is too old: make a new plan.")
            if self._run.get("active"):
                raise Refused("A run is active.")
            self._plan = None
            self._cancel.clear()
            self._run = dict(active=True, plan_id=plan["id"], summary=plan["summary"], direction=plan["direction"],
                             steps=plan["labels"], step=None, done=[], ok=None, error="", moving=False,
                             started_moving_at=None, progress=0, started_at=self._clock(), finished_at=None,
                             message="Starting.")
            self._thread = threading.Thread(target=self._execute, args=(plan,), daemon=True, name="arm-run")
            self._thread.start()
            return dict(ok=True, run=dict(self._run))

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- inside ---

    def _require_idle(self, what: str) -> None:
        with self._lock:
            if self._run.get("active"):
                raise Refused(f"{what} is refused while the arm runs a plan.")

    def _update(self, **fields) -> None:
        with self._lock:
            self._run.update(fields)

    def _execute(self, plan: dict) -> None:
        log = self._log(plan)
        stopped = self._cancel.is_set
        cfg = self._cfg or _cfg()
        expected_e1 = None
        capability_checked = False
        steps = plan["steps"]
        uploaded: dict | None = None  # the next queue, uploaded while the grip settled
        checked_early: set[int] = set()  # Squid checks made while the grip settled
        try:
            for index, step in enumerate(steps):
                self._update(step=step["label"], moving=False, progress=0, message=step["label"])
                log("step", label=step["label"], kind=step["kind"])
                if stopped():
                    raise MotionError("Stopped by the operator.")
                if index in checked_early:
                    with self._lock:
                        self._run["done"] = self._run["done"] + [step["label"]]
                    log("done", label=step["label"], during_grip=True)
                    continue
                if step["kind"] == "queue":
                    expected_e1 = step["e1"]  # empty (7) or holding the plate (3.9): checked before the move
                s, n = state(self.service, expected_e1)  # the one read between two steps
                if step["kind"] == "jaws":
                    jaws(self.service, routes.EMPTY_E1, 5, s["pose_mm"], stopped)
                    expected_e1 = routes.EMPTY_E1
                elif step["kind"] == "queue":
                    expected = routes.check_queue(s["pose_mm"], s["joints"], step["points"], cfg, self.service.envelope)

                    def started(label=step["label"]):
                        now = self._clock()
                        with self._lock:
                            self._run.update(moving=True, message="The arm is moving: " + label)
                            if self._run.get("started_moving_at") is None:
                                self._run["started_moving_at"] = now
                        log("moving", label=label)

                    ready = uploaded if uploaded and uploaded["index"] == index else None
                    uploaded = None
                    run_queue(self.service, step["points"], step["speeds"], expected, cfg, stopped, started,
                              lambda percent: self._update(progress=round(percent)),
                              capability_checked=capability_checked, uploaded=ready)
                    capability_checked = True  # once per run
                    self._update(moving=False)
                elif step["kind"] in ("grip", "release"):
                    # The next move is uploaded while the arm stands still: for a grip, during the settle check
                    # (only reads) after the jaws closed; for a release, before the jaws open, so that only a short
                    # check remains after them. Before the move the controller must still hold it exactly (else it
                    # is uploaded again); nothing moves until then.
                    later = index + 1
                    while later < len(steps) and steps[later]["kind"] == "squid":
                        later += 1
                    nxt = steps[later] if later < len(steps) and steps[later]["kind"] == "queue" else None

                    def upload_next():
                        nonlocal uploaded, capability_checked
                        if nxt is not None:
                            uploaded = dict(upload_queue(self.service, nxt["points"], nxt["speeds"], stopped,
                                                         capability_checked), index=later)
                            capability_checked = True
                            log("uploaded", label=nxt["label"])

                    self._update(moving=True, message=step["label"])
                    if step["kind"] == "grip":
                        close_on_plate(self.service, s["pose_mm"], stopped)
                        expected_e1 = routes.GRIP_E1
                        with ThreadPoolExecutor(max_workers=2) as pool:  # only reads, beside the upload
                            settled = pool.submit(settle, self.service, s["pose_mm"])
                            squid = [pool.submit(self._squid_check) for _ in range(index + 1, later)]
                            upload_next()
                            settled.result()
                            for check in squid:
                                check.result()
                        checked_early.update(range(index + 1, later))
                    else:
                        upload_next()
                        closing = command_jaws(self.service, routes.EMPTY_E1, routes.RELEASE_SPEED, stopped)
                        expected_e1 = routes.EMPTY_E1
                        arrived(self.service, routes.EMPTY_E1, closing, s["pose_mm"])
                elif step["kind"] == "squid":
                    self._squid_check()
                else:
                    raise MotionError("Unknown step.")
                with self._lock:
                    self._run["done"] = self._run["done"] + [step["label"]]
                log("done", label=step["label"])
            if plan["direction"] == "recover":
                message = "Done: the empty arm is parked at the safe position. Check where the plate is."
                self._update(active=False, ok=True, moving=False, step=None, message=message,
                             finished_at=self._clock())
                log("finished", ok=True)
                return
            at = "Squid" if plan["direction"] == "load" else f"slot {plan['slot']}"
            self.plate = dict(at=at, since=self._clock(), plan_id=plan["id"])
            message = f"Done: the plate is at {at}; the empty arm is parked at the safe position."
            self._update(active=False, ok=True, moving=False, step=None, message=message,
                         finished_at=self._clock())
            log("finished", ok=True, plate_at=at)
        except Exception as error:  # noqa: BLE001  a stopped or failed run: the person looks at the arm
            self.plate = None  # unknown until a person says where it is
            message = f"Stopped: {error}"
            self._update(active=False, ok=False, moving=False, error=str(error), message=message,
                         finished_at=self._clock())
            log("finished", ok=False, error=str(error))
        finally:
            self._status = (0.0, {})

    def _log(self, plan: dict):
        folder = self._runs / time.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{plan['id']}.jsonl"

        def write(event: str, **fields) -> None:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(at=self._clock(), event=event, **fields), default=str) + "\n")

        write("plan", plan=plan)
        return write
