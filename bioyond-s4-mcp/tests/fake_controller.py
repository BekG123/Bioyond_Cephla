"""Minimal fake Bioyond controller for offline testing of the BRCAPI client.

Emulates the deployed main.bin contract (mod_Socket):
- SysVarI 0=device 1-3=pos 4=movetype 5=obj 6=clamp
- device 21 = host-point extension (SysParaF 0-6) when hostpoint_supported
- device 3 = taught homing job; stations 11..15/9998/9999 = taught jobs
- unmatched device >10 replies SysOutVar (1, -1) like mod_EndInvalid
- pose query reports METERS; getSysParaF returns values as STRINGS
  (both quirks observed on the live controller)

Deliberately fragments frames to prove the client's receive buffer works.
"""

from __future__ import annotations

import json
import math
import socket
import threading
import time


class FakeController:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        # controller convention (verified live): meters + RADIANS
        self.pose = {"X": 0.300, "Y": -0.050, "Z": 0.370,
                     "Rx": 0.0, "Ry": 0.0, "Rz": math.radians(90.0)}
        self.joints = [250.0, 0.0, 0.0, 0.0]
        self.e1 = 28.0
        self._e1_cmd = 28.0
        self.object_width = 23.34   # reported E1 stalls here (measured)
        self.free_torque = 160.0    # positive free-motion baseline (measured)
        self.grip_torque = -187.0   # saturated squeeze torque (measured)
        self.mode = 1        # auto
        self.enabled = 1
        self.prog_state = 1  # running
        self.lua_ready = 1
        self.sys_state = 1   # idle
        self.errors: list[dict] = []
        self.para_f: dict[int, float] = {}
        self.var_i: dict[int, int] = {}
        self.hostpoint_supported = True
        self.job_log: list[dict] = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self._srv.accept()
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self._handle(conn, json.loads(line.decode("utf-8")))

    def _send(self, conn: socket.socket, obj: dict) -> None:
        data = (json.dumps(obj) + "\n").encode("utf-8")
        mid = max(1, len(data) // 2)  # fragment to test the receive buffer
        conn.sendall(data[:mid])
        time.sleep(0.005)
        conn.sendall(data[mid:])

    def _handle(self, conn: socket.socket, req: dict) -> None:
        cmd, fid, params = req.get("cmd"), req.get("id"), req.get("params")
        api = {"BRCAPI": "1.0", "id": fid}

        def ret(value):
            self._send(conn, {**api, "ret": value})

        if cmd == "getSysState":
            ret({"value": self.sys_state})
        elif cmd == "getCtrlMode":
            ret({"value": self.mode})
        elif cmd == "getEnableStatus":
            ret({"value": self.enabled})
        elif cmd == "getProgState":
            ret({"value": self.prog_state})
        elif cmd == "getLuaAppStatus":
            ret({"value": self.lua_ready})
        elif cmd == "getRobotErr":
            ret(self.errors or [{"errCode": None, "errMsg": None}])
        elif cmd == "getFrameWithU0T0":
            ret(dict(self.pose))
        elif cmd == "getJointInfo":
            ret({
                "joints": [{"index": i, "value": v} for i, v in enumerate(self.joints)],
                "extjoint": [],
            })
        elif cmd == "getSysParaF":
            # live controller returns strings
            ret([{"index": p["index"], "value": f"{self.para_f.get(p['index'], 0.0):.6f}"}
                 for p in params])
        elif cmd == "getSysParaI":
            ret([{"index": p["index"], "value": 0} for p in params])
        elif cmd == "getSysVarI":
            ret([{"index": p["index"], "value": self.var_i.get(p["index"], 0)}
                 for p in params])
        elif cmd == "setSysParaF":
            for p in params:
                self.para_f[p["index"]] = float(p["value"])
            ret(None)
        elif cmd == "setSysParaI":
            ret(None)
        elif cmd in ("switchToAuto", "switchToManual", "remoteEnable",
                     "remoteDisable", "remoteStart", "remotePause",
                     "remoteStop", "remoteClearError"):
            if cmd == "switchToAuto":
                self.mode = 1
            elif cmd == "switchToManual":
                self.mode = 0
            elif cmd == "remoteEnable":
                self.enabled = 1
            elif cmd == "remoteDisable":
                self.enabled = 0
            elif cmd == "remoteStart":
                self.prog_state = 1
            elif cmd == "remoteStop":
                self.prog_state = 0
            elif cmd == "remoteClearError":
                self.errors = []
            ret(None)
            time.sleep(0.02)
            self._send(conn, {**api, "reply": "CmdDone"})
        elif cmd == "setSysVarI":
            for p in params:
                self.var_i[p["index"]] = p["value"]
            ret(None)
            threading.Thread(
                target=self._run_socket_loop, args=(conn, api), daemon=True
            ).start()
        else:
            self._send(conn, {**api,
                              "error": {"code": 2, "message": "Invalid command name"}})

    def _grip_torque(self) -> float:
        """Free motion = positive baseline; squeezing = negative saturation."""
        if self.e1 - self._e1_cmd <= 0.05:
            return self.free_torque
        return self.grip_torque

    def _write_grip_report(self) -> None:
        trq = self._grip_torque()
        self.var_i[10] = int(round(self.e1 * 1000))
        self.var_i[11] = int(round(trq * 1000))
        self.var_i[12] = int(round(trq / 100.0 * 1000))

    def _reply_out(self, conn, api, value: int) -> None:
        for k in range(7):  # mod_End/EndInvalid reset vars 0-6 only
            if k in self.var_i:
                self.var_i[k] = 0
        self._send(conn, {**api, "reply": {"index": 1, "value": value}})

    def _run_socket_loop(self, conn: socket.socket, api: dict) -> None:
        time.sleep(0.05)  # "motion"
        dev = self.var_i.get(0, 0)
        mtype = self.var_i.get(4, 0)
        self.job_log.append({"vars": dict(self.var_i)})
        if dev == 21 and self.var_i.get(1) == 1 and mtype != 0:
            if not self.hostpoint_supported:
                self._reply_out(conn, api, -1)
                return
            g = self.para_f.get
            if mtype in (1, 2):      # MoveL / MoveJ, host sends mm
                self.pose["X"] = g(0, self.pose["X"] * 1000.0) / 1000.0
                self.pose["Y"] = g(1, self.pose["Y"] * 1000.0) / 1000.0
                self.pose["Z"] = g(2, self.pose["Z"] * 1000.0) / 1000.0
                self.pose["Rz"] = math.radians(g(3, math.degrees(self.pose["Rz"])))
            elif mtype == 3:         # gripper
                self._e1_cmd = g(6, self.e1)
                self.e1 = max(self._e1_cmd, self.object_width)
                self._write_grip_report()
            elif mtype == 4:         # MoveAbsJ
                self.joints = [g(0, 0.0), g(1, 0.0), g(2, 0.0), g(3, 0.0)]
            elif mtype == 5:         # report only
                self._write_grip_report()
            elif mtype == 6:         # force-limited close: stops at object
                self._e1_cmd = g(6, self.e1)
                self.e1 = max(self._e1_cmd, self.object_width)
                self._write_grip_report()
            self._reply_out(conn, api, 1)
        elif dev == 3:               # taught homing job
            self.joints = [66.75, 8.38, 105.69, 0.0] if self.var_i.get(1) == 1 \
                else [250.0, 0.0, 0.0, 0.0]
            self._reply_out(conn, api, 1)
        elif dev in (11, 12, 13, 14, 15, 9998, 9999):
            self._reply_out(conn, api, 1)
        elif dev > 10:
            self._reply_out(conn, api, -1)
        else:
            # unmatched low device ids are silently ignored by mod_Socket;
            # vars stay set and no reply is ever sent
            pass
