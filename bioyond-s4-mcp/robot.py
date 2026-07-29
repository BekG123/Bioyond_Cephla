"""Hardened BRCAPI (Rob INTF v1.1) TCP client for the Bioyond LabGenius S4.

The controller is a TCP server (port 56788) speaking newline-terminated UTF-8
JSON frames. Only one client may be connected at a time.

This client fixes the known problems in the vendor reference code:
- persistent receive buffer that handles partial frames and multiple frames
  per socket read
- every response correlated by ``id`` (ack frame and later result-reply frame)
- correct mode values (Manual=0, Auto=1) and program state Error=3
- a timeout NEVER implies the command was not executed; motion timeouts raise
  UnknownStateError so callers do not blindly resend
"""

from __future__ import annotations

import itertools
import json
import logging
import socket
import threading
from queue import Empty, Queue
from typing import Any, Optional

log = logging.getLogger("bioyond.robot")

BRCAPI_VERSION = "1.0"
DEFAULT_PORT = 56788

# getCtrlMode (protocol values — the vendor Python sample has these reversed)
MODE_MANUAL = 0
MODE_AUTO = 1

PROG_STATES = {0: "stopped", 1: "running", 2: "paused", 3: "error"}
SYS_STATES = {0: "init", 1: "idle", 2: "running", 3: "error", 4: "paused", 5: "enabled"}


class RobotError(Exception):
    """Base class for robot client errors."""


class NotConnectedError(RobotError):
    pass


class AckError(RobotError):
    """Controller acknowledged the frame with an error object."""

    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"controller error {code}: {message}")


class ResponseTimeout(RobotError):
    """No response frame arrived in time (query/ack level)."""


class UnknownStateError(RobotError):
    """A motion/execution command timed out or the link dropped mid-command.

    The command MAY still be executing on the controller. Do not resend it;
    re-query robot state first.
    """


class _Pending:
    def __init__(self) -> None:
        self.queue: Queue = Queue()


class RobotClient:
    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._ip: Optional[str] = None
        self._port: Optional[int] = None
        self._ids = itertools.count(1)
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._rx_thread: Optional[threading.Thread] = None
        self.unsolicited: list[dict] = []  # frames we could not correlate

    # ------------------------------------------------------------------ link

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def endpoint(self) -> Optional[str]:
        if self._ip is None:
            return None
        return f"{self._ip}:{self._port}"

    def connect(self, ip: str, port: int = DEFAULT_PORT, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._connected:
                raise RobotError(
                    f"already connected to {self.endpoint}; disconnect first "
                    "(the controller only accepts one client)"
                )
            sock = socket.create_connection((ip, port), timeout=timeout)
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = sock
            self._ip, self._port = ip, port
            self._connected = True
            self._rx_thread = threading.Thread(
                target=self._rx_loop, name="brcapi-rx", daemon=True
            )
            self._rx_thread.start()
        log.info("connected to %s:%s", ip, port)

    def disconnect(self) -> None:
        with self._state_lock:
            self._connected = False
            if self._sock is not None:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
        self._fail_all_pending()
        log.info("disconnected")

    def _fail_all_pending(self) -> None:
        with self._pending_lock:
            pendings = list(self._pending.values())
        for p in pendings:
            p.queue.put(None)  # sentinel: link lost

    # ------------------------------------------------------------- rx loop

    def _rx_loop(self) -> None:
        buf = b""
        sock = self._sock
        while self._connected and sock is not None:
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:  # server closed
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self._dispatch(line)
        was_connected = self._connected
        self._connected = False
        self._fail_all_pending()
        if was_connected:
            log.warning("connection to controller lost")

    def _dispatch(self, line: bytes) -> None:
        try:
            frame = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.error("unparseable frame: %r", line[:200])
            return
        fid = frame.get("id", -1)
        with self._pending_lock:
            pending = self._pending.get(fid)
        if pending is not None:
            pending.queue.put(frame)
        else:
            self.unsolicited.append(frame)
            del self.unsolicited[:-50]  # keep bounded

    # ------------------------------------------------------------- requests

    def _send_frame(self, cmd: str, params: Any) -> tuple[int, _Pending]:
        if not self._connected or self._sock is None:
            raise NotConnectedError("not connected to the robot controller")
        fid = next(self._ids)
        frame: dict[str, Any] = {"BRCAPI": BRCAPI_VERSION, "cmd": cmd, "id": fid}
        if params is not None:
            frame["params"] = params
        pending = _Pending()
        with self._pending_lock:
            self._pending[fid] = pending
        data = (json.dumps(frame) + "\n").encode("utf-8")
        try:
            with self._send_lock:
                self._sock.sendall(data)
        except OSError as ex:
            self._unregister(fid)
            self._connected = False
            raise NotConnectedError(f"send failed: {ex}") from ex
        return fid, pending

    def _unregister(self, fid: int) -> None:
        with self._pending_lock:
            self._pending.pop(fid, None)

    @staticmethod
    def _check_ack(frame: dict, cmd: str) -> dict:
        err = frame.get("error")
        if err is not None:
            raise AckError(err.get("code"), f"{err.get('message')} (cmd={cmd})")
        return frame

    def request(self, cmd: str, params: Any = None, timeout: float = 5.0) -> dict:
        """Send a command and return its first response frame (ack/return)."""
        fid, pending = self._send_frame(cmd, params)
        try:
            frame = pending.queue.get(timeout=timeout)
        except Empty:
            raise ResponseTimeout(f"no response to {cmd} within {timeout}s") from None
        finally:
            self._unregister(fid)
        if frame is None:
            raise NotConnectedError(f"connection lost while waiting for {cmd} response")
        return self._check_ack(frame, cmd)

    def request_with_reply(
        self,
        cmd: str,
        params: Any = None,
        ack_timeout: float = 5.0,
        reply_timeout: float = 30.0,
    ) -> dict:
        """Send a command that produces an ack frame plus a later result reply.

        Returns the result-reply frame. On timeout after a successful ack the
        command may still be executing — raises UnknownStateError.
        """
        fid, pending = self._send_frame(cmd, params)
        try:
            try:
                ack = pending.queue.get(timeout=ack_timeout)
            except Empty:
                raise UnknownStateError(
                    f"{cmd}: no acknowledgement within {ack_timeout}s — "
                    "the command may or may not have been received; re-query "
                    "state before retrying"
                ) from None
            if ack is None:
                raise UnknownStateError(f"{cmd}: connection lost before acknowledgement")
            self._check_ack(ack, cmd)
            if "reply" in ack:  # some stacks answer in a single frame
                return ack
            try:
                reply = pending.queue.get(timeout=reply_timeout)
            except Empty:
                raise UnknownStateError(
                    f"{cmd}: acknowledged but no completion reply within "
                    f"{reply_timeout}s — the robot may still be executing it. "
                    "Do NOT resend; query state/pose first."
                ) from None
            if reply is None:
                raise UnknownStateError(
                    f"{cmd}: connection lost while the command was executing — "
                    "physical state unknown"
                )
            return self._check_ack(reply, cmd)
        finally:
            self._unregister(fid)

    # ------------------------------------------------------------- queries

    def get_sys_state(self) -> dict:
        val = self.request("getSysState")["ret"]["value"]
        return {"value": val, "state": SYS_STATES.get(val, f"unknown({val})")}

    def get_ctrl_mode(self) -> dict:
        val = self.request("getCtrlMode")["ret"]["value"]
        return {"value": val, "mode": {0: "manual", 1: "auto"}.get(val, f"unknown({val})")}

    def get_enable_status(self) -> bool:
        return self.request("getEnableStatus")["ret"]["value"] == 1

    def get_prog_state(self) -> dict:
        val = self.request("getProgState")["ret"]["value"]
        return {"value": val, "state": PROG_STATES.get(val, f"unknown({val})")}

    def get_lua_app_status(self) -> bool:
        return self.request("getLuaAppStatus")["ret"]["value"] == 1

    def get_robot_errors(self) -> list[dict]:
        ret = self.request("getRobotErr")["ret"]
        errors = []
        for item in ret or []:
            if item.get("errCode") is not None:
                errors.append({"errCode": item["errCode"], "errMsg": item.get("errMsg")})
        return errors

    def get_joint_info(self) -> dict:
        ret = self.request("getJointInfo")["ret"]
        joints = {f"J{j['index'] + 1}": j["value"] for j in ret.get("joints", [])}
        ext = {f"E{j['index'] + 1}": j["value"] for j in ret.get("extjoint", [])}
        return {"joints": joints, "external": ext}

    def get_cartesian_pose(self) -> dict:
        """Current TCP pose in the default tool (T0) / user (U0) frame."""
        return dict(self.request("getFrameWithU0T0")["ret"])

    def get_sys_var_i(self, indexes: list[int]) -> dict[int, int]:
        ret = self.request("getSysVarI", [{"index": i} for i in indexes])["ret"]
        return {item["index"]: item["value"] for item in ret}

    def get_sys_para_i(self, indexes: list[int]) -> dict[int, int]:
        ret = self.request("getSysParaI", [{"index": i} for i in indexes])["ret"]
        # the live controller returns numeric values as strings
        return {item["index"]: int(float(item["value"])) for item in ret}

    def get_sys_para_f(self, indexes: list[int]) -> dict[int, float]:
        ret = self.request("getSysParaF", [{"index": i} for i in indexes])["ret"]
        return {item["index"]: float(item["value"]) for item in ret}

    # ------------------------------------------------------------- control

    def switch_mode(self, auto: bool, timeout: float = 10.0) -> str:
        cmd = "switchToAuto" if auto else "switchToManual"
        return str(self.request_with_reply(cmd, reply_timeout=timeout)["reply"])

    def set_enable(self, enable: bool, timeout: float = 10.0) -> str:
        cmd = "remoteEnable" if enable else "remoteDisable"
        return str(self.request_with_reply(cmd, reply_timeout=timeout)["reply"])

    def clear_errors(self, timeout: float = 10.0) -> str:
        return str(self.request_with_reply("remoteClearError", reply_timeout=timeout)["reply"])

    def prog_start(self, timeout: float = 10.0) -> str:
        return str(self.request_with_reply("remoteStart", reply_timeout=timeout)["reply"])

    def prog_pause(self, timeout: float = 10.0) -> str:
        return str(self.request_with_reply("remotePause", reply_timeout=timeout)["reply"])

    def prog_stop(self, timeout: float = 10.0) -> str:
        return str(self.request_with_reply("remoteStop", reply_timeout=timeout)["reply"])

    def move_backwards(self, timeout: float = 120.0) -> str:
        return str(self.request_with_reply("moveBackwards", reply_timeout=timeout)["reply"])

    def stop_move_backwards(self, timeout: float = 10.0) -> str:
        return str(self.request_with_reply("stopMoveBackwards", reply_timeout=timeout)["reply"])

    def set_sys_para_i(self, values: dict[int, int]) -> None:
        params = [{"index": int(k), "value": int(v)} for k, v in values.items()]
        self.request("setSysParaI", params)

    def set_sys_para_f(self, values: dict[int, float]) -> None:
        params = [{"index": int(k), "value": float(v)} for k, v in values.items()]
        self.request("setSysParaF", params)

    def set_sys_var_i(self, values: dict[int, int], reply_timeout: float = 300.0) -> Any:
        """Set system variables and wait for the Lua result reply.

        In the Bioyond contract, setSysVarI triggers the Lua program to run a
        piece of motion, and the result reply arrives only when it finishes.
        """
        params = [{"index": int(k), "value": int(v)} for k, v in values.items()]
        frame = self.request_with_reply(
            "setSysVarI", params, reply_timeout=reply_timeout
        )
        return frame["reply"]
