"""HTTP for the arm service, on this computer only (127.0.0.1). The microscope notebook calls it.

    python -m arm_service.server [--port 5004] [--no-connect]

GET  /api/state                   robot, the plan that waits, the run, where the plate is
POST /api/connect                 connect the robot (nothing moves)
POST /api/plans                   {"direction": "load"|"unload", "slot": 1}: a plan; nothing moves
POST /api/plans/<id>/start        a person starts the plan that waits (someone is at the E-stop)
POST /api/plans/<id>/cancel       drop the plan that waits
POST /api/stop                    stop the controller program now (also with no run)
POST /api/clear_errors            clear the controller's errors (refused while a run is active)
POST /api/program/start           start the controller program after a Stop (refused while the jaws hold a plate)

A refusal answers 409 with {"ok": false, "error": ...}: nothing was sent to the arm.
"""
from __future__ import annotations

import argparse
import logging

import flask

from arm_service.service import ArmService, Refused


def create_app(arm: ArmService) -> flask.Flask:
    app = flask.Flask(__name__)

    def answer(action):
        try:
            return flask.jsonify({"ok": True, **action()})  # an action may say ok false itself (errors remain)
        except Refused as error:
            return flask.jsonify(ok=False, error=str(error)), 409
        except Exception as error:  # noqa: BLE001  the outcome is not known: the page says so, nothing is retried
            logging.exception("arm service request failed")
            return flask.jsonify(ok=False, error=str(error), outcome="unknown"), 500

    def body() -> dict:
        return flask.request.get_json(silent=True) or {}

    @app.before_request
    def local_only():
        if flask.request.remote_addr not in ("127.0.0.1", "::1"):
            return flask.jsonify(ok=False, error="local only"), 403
        return None

    @app.get("/api/state")
    def state():
        return answer(arm.state)

    @app.post("/api/connect")
    def connect():
        return answer(arm.connect)

    @app.post("/api/plans")
    def plans():
        data = body()
        return answer(lambda: dict(plan=arm.plan(str(data.get("direction", "")), data.get("slot", 1))))

    @app.post("/api/plans/<plan_id>/start")
    def start(plan_id):
        return answer(lambda: arm.start(plan_id))

    @app.post("/api/plans/<plan_id>/cancel")
    def cancel(plan_id):
        return answer(lambda: arm.cancel_plan(plan_id))

    @app.post("/api/stop")
    def stop():
        return answer(arm.stop)

    @app.post("/api/clear_errors")
    def clear_errors():
        return answer(arm.clear_errors)

    @app.post("/api/program/start")
    def program_start():
        return answer(arm.start_program)

    return app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="The simple arm service (slot 1 <-> microscope).")
    parser.add_argument("--port", type=int, default=5004)
    parser.add_argument("--no-connect", action="store_true", help="do not connect the robot at start")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    arm = ArmService()
    if not args.no_connect:
        try:
            arm.connect()
        except Exception as error:  # noqa: BLE001  the page shows Connect; nothing else depends on it
            logging.warning("the robot did not connect at start: %s", error)
    print(f"arm service on http://127.0.0.1:{args.port}/", flush=True)
    create_app(arm).run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
