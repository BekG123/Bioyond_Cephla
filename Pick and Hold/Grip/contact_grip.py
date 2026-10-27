"""Offline E1 contact controller candidate; no hardware imports or dispatch.

One proposal, one acknowledged increment, then stationary observations. The
caller must preserve all other axes, existing drive protection and ownership,
and handle Stop/timeouts while an increment is in flight. This algorithm cannot
limit effort during a position move. It must not be wired to unattended Grip
until its reference data and physical stopping behaviour are commissioned.
"""
from dataclasses import dataclass
import math


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite numeric feedback required')
    return float(value)


@dataclass(frozen=True)
class Reference:
    # Position-dependent, same-pose/speed empty-claw measurements. No ForceArray.
    e1_mm: float
    empty_torque: float
    contact_delta: float


class ContactGrip:
    """Pure state machine for supervised, increment-by-increment commissioning.

    contact_delta must come from distinguishable empty/contact measurements;
    it is NOT derived from the old 3.8 mm position or treated as a force limit.
    Absolute change recognizes an anomaly in either direction. A candidate
    stops closing immediately; fresh stationary samples confirm persistence,
    not a secure grasp. Every decision still requires human inspection.
    """
    FLOOR = 3.8
    STEP = .1
    SPEED = 5
    TOLERANCE = .05
    MAX_AGE = .5

    def __init__(self, references, *, source, commissioned=False):
        if commissioned is not True or not isinstance(source, str) or not source.strip():
            raise ValueError('Reviewed empirical reference data required')
        self.references = tuple(references)
        if not self.references:
            raise ValueError('Empty-claw and contact references required')
        for ref in self.references:
            if not isinstance(ref, Reference):
                raise ValueError('Invalid reference')
            if not self.FLOOR <= number(ref.e1_mm) <= 28.05:
                raise ValueError('Reference outside E1 range')
            number(ref.empty_torque)
            if number(ref.contact_delta) <= 0:
                raise ValueError('Measured positive contact separation required')
        self.source = source
        self.state = 'ready'
        self.last_sequence = -1
        self.pending = None
        self.observed = None
        self.contact_samples = 0

    def _reference(self, e1):
        ref = min(self.references, key=lambda r: abs(r.e1_mm-e1))
        if abs(ref.e1_mm-e1) > self.TOLERANCE + 1e-9:
            raise ValueError('No local empty/contact reference at this opening')
        return ref

    def stop(self, reason):
        self.state = 'stopped'
        self.pending = None
        return dict(state=self.state, reason=reason, move=None, grasp_verified=False)

    def observe(self, sample):
        """sample is an acknowledged FRESH stationary report, not cached slots.

        Required: sequence, age_s, e1_mm, torque, stationary, healthy,
        pose_unchanged, other_axes_unchanged, recovered. The transport adapter
        must establish freshness from a completed report request, not invent it.
        """
        if self.state in ('stopped', 'contact_candidate', 'floor_reached'):
            return dict(state=self.state, move=None, grasp_verified=False)
        try:
            seq = sample['sequence']
            if type(seq) is not int or seq <= self.last_sequence:
                raise ValueError('Stale or duplicate report')
            if not 0 <= number(sample['age_s']) <= self.MAX_AGE:
                raise ValueError('Feedback too old')
            for key in ('healthy', 'stationary', 'pose_unchanged', 'other_axes_unchanged'):
                if sample.get(key) is not True:
                    raise ValueError('Fault, motion or changed pose: '+key)
            if sample.get('recovered') is not False:
                raise ValueError('Uncertain command/report completion')
            e1, torque = number(sample['e1_mm']), number(sample['torque'])
            if not self.FLOOR-self.TOLERANCE <= e1 <= 28.05:
                raise ValueError('Opening outside permitted range')
            if self.pending is not None and abs(e1-self.pending) > self.TOLERANCE:
                raise ValueError('Increment did not reach target; inspect stall')
            if self.pending is None and self.observed is not None and abs(e1-self.observed) > self.TOLERANCE:
                raise ValueError('Uncommanded E1 change; inspect before continuing')
            ref = self._reference(e1)
            self.last_sequence, self.observed, self.pending = seq, e1, None
            delta = abs(torque-ref.empty_torque)
            if delta >= ref.contact_delta:
                self.contact_samples += 1
                self.state = 'contact_candidate' if self.contact_samples >= 3 else 'observing_contact'
            elif self.state == 'observing_contact':
                return self.stop('Transient torque change; inspect before any further closure')
            elif e1 <= self.FLOOR + .001:
                self.state = 'floor_reached'
            else:
                self.state = 'ready'
            return dict(state=self.state, torque_delta=delta, move=None,
                        grasp_verified=False, inspection_required=self.state!='ready')
        except (ValueError, KeyError, TypeError) as error:
            return self.stop(str(error))

    def propose_increment(self, *, confirmed=False):
        """Returns a proposal only. Never sends a command or clears a stop."""
        if confirmed is not True:
            raise ValueError('Explicit confirmation required for each trial increment')
        if self.state != 'ready' or self.observed is None or self.pending is not None:
            raise ValueError('A fresh stationary report is required before closing')
        target = max(self.FLOOR, round(self.observed-self.STEP, 3))
        if target >= self.observed:
            raise ValueError('No further closure permitted')
        self._reference(target)  # Missing baseline cannot cause an exploratory move.
        self.pending, self.state = target, 'awaiting_completion'
        return dict(e1_mm=target, speed=self.SPEED, max_step_mm=self.STEP,
                    dispatch=False, requires_supervised_transport=True)
