"""Where each plate is. Checked before every transfer, updated after it."""
from __future__ import annotations

from .events import iso

LOCATIONS = ('bioyond deck', 'hamilton', 'squid stage', 'gripper', 'unknown')


class Ledger:
    def __init__(self, run):
        self.run = run

    def plates(self):
        return (self.run.read_json('ledger.json') or {}).get('plates', {})

    def location(self, plate):
        return self.plates().get(plate, {}).get('location')

    def problem(self, transfer):
        """Why this transfer must not start, or None."""
        if not isinstance(transfer, dict) or any(k not in transfer for k in ('plate', 'from', 'to')):
            return "A transfer needs 'plate', 'from' and 'to'."
        plate, source, target = transfer['plate'], transfer['from'], transfer['to']
        if source not in LOCATIONS or target not in LOCATIONS or 'unknown' in (source, target):
            return f"Locations must be one of {', '.join(LOCATIONS[:-1])}."
        current = self.location(plate)
        if current is None:
            return f"Plate '{plate}' is not in the ledger."
        if current != source:
            return f"Plate '{plate}' is recorded at '{current}', but this step expects it at '{source}'."
        return None

    def move(self, transfer, step_id, now):
        self._set(transfer['plate'], transfer['to'], step_id, now)

    def mark_unknown(self, transfer, step_id, now):
        self._set(transfer['plate'], 'unknown', step_id, now)

    def _set(self, plate, location, step_id, now):
        plates = self.plates()
        plates[plate] = dict(location=location, step=step_id, ts=iso(now))
        self.run.write_json('ledger.json', dict(plates=plates))
