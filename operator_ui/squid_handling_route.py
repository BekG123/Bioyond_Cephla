"""Pinned robot routes for handling; loading this module never contacts hardware."""
import json
from pathlib import Path
from capture_squid_approach_20261103 import FOLDER, sha

LEGACY_SOURCE = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
LEGACY_SHA = '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81'
CURRENT_SOURCE = FOLDER / 'final_squid_candidate_20261108.json'
CURRENT_SHA = '9805c608b92e8efcd2c046f5f06b50d79b63d7ae61ee95dcb6c948af6050d3ff'


def load_route(source=LEGACY_SOURCE, expected_sha=LEGACY_SHA):
    source = Path(source)
    if sha(source) != expected_sha:
        raise RuntimeError('Reviewed Squid route changed')
    plan = json.loads(source.read_bytes())
    points = plan['routes']['from_capture']
    if len(points) == 5:
        # The newly taught route is forward-only; return is its exact reverse.
        points = points + list(reversed(points[:-1]))
    if len(points) != 9 or points[4:] != list(reversed(points[:5])):
        raise RuntimeError('Expected reviewed forward route and exact reverse')
    plan['routes'] = {'from_capture': points}
    plan['leg_speeds'] = [137, 137, 137, 5, 5, 137, 137, 137]
    plan['route_source'] = str(source)
    plan['route_source_sha256'] = expected_sha
    return plan
