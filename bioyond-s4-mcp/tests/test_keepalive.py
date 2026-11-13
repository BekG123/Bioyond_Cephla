"""Offline test of the keepalive: an idle link gets a read-only getRobotErr, a busy link
gets none, and the keepalive ends with the link. Run: py tests/test_keepalive.py"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_controller import FakeController  # noqa: E402
from robot import RobotClient  # noqa: E402


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        sys.exit(1)


def frames(fake, cmd, since):
    return [t for t, c in list(fake.cmd_log) if c == cmd and t >= since]


def main():
    interval = 0.2

    # 1. An idle link: one getRobotErr about every interval, nothing else.
    fake = FakeController()
    client = RobotClient(keepalive_s=interval)
    client.connect("127.0.0.1", fake.port)
    start = time.monotonic()
    time.sleep(1.1)
    sent = frames(fake, "getRobotErr", start)
    others = [c for t, c in list(fake.cmd_log) if t >= start and c != "getRobotErr"]
    check("idle link gets keepalive reads", 3 <= len(sent) <= 7, f"({len(sent)} in 1.1 s)")
    check("keepalive sends only getRobotErr", not others, str(others))
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    check("no keepalive burst", all(g >= interval * 0.8 for g in gaps), str([round(g, 3) for g in gaps]))

    # 2. A busy link (a read every 50 ms, like motion monitoring): no keepalive at all.
    start = time.monotonic()
    while time.monotonic() - start < 1.0:
        client.get_cartesian_pose()
        time.sleep(0.05)
    check("busy link gets no keepalive", not frames(fake, "getRobotErr", start))

    # 3. After disconnect the keepalive stops.
    client.disconnect()
    time.sleep(0.05)
    after = time.monotonic()
    time.sleep(0.6)
    check("no keepalive after disconnect", not frames(fake, "getRobotErr", after))

    # 4. keepalive_s=None: an idle link stays silent (old behaviour).
    fake2 = FakeController()
    quiet = RobotClient(keepalive_s=None)
    quiet.connect("127.0.0.1", fake2.port)
    start = time.monotonic()
    time.sleep(0.6)
    check("keepalive can be switched off", not frames(fake2, "getRobotErr", start))
    quiet.disconnect()

    # 5. The default is on.
    check("default keepalive is on", RobotClient()._keepalive_s and RobotClient()._keepalive_s <= 5)
    print("ALL PASS")


if __name__ == "__main__":
    main()
