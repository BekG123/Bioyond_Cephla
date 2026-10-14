"""Original two-circle teach loop, with current motion checks at its boundary."""
import math

from autonomy import TransferError, check_path, number, wrap
from fast_disk import DiskGuard


class OriginalDiskGuard(DiskGuard):
    rotation_speed = 5  # Keep the original stage's cap independent of Fast SPEED.

    @property
    def envelope_enabled(self):
        return self.service.envelope_enabled

    @property
    def envelope(self):
        return self.service.envelope

    def joints(self):
        self._preflight()
        return self.service.joints()

    def move_cartesian(self, x, y, z, rz, speed=5, interpolation='linear'):
        start = self.pose_mm()
        if abs(wrap(rz-start['Rz'])) > .05 and min(start['Z'], z) < 300:
            raise TransferError('original disk wrist correction requires TCP Z >=300 mm; no automatic lift')
        return super().move_cartesian(x, y, z, rz, min(speed, 5), interpolation)

    def rotate_to_rz(self, rz, speed=5, force_delta=None):
        start = self.pose_mm()
        delta = number(force_delta if force_delta is not None else wrap(rz-start['Rz']), 'wrist delta')
        if abs(delta) > 360:
            raise TransferError('original disk winding exceeds one turn')
        # Preserve the original chosen winding; preflight every segment before
        # dispatching any, then use the current checked pure-wrist driver.
        n = max(1, math.ceil(abs(delta)/10))
        pose, joints = start, self.joints() or {}
        goals = []
        for i in range(1, n+1):
            goal = {**start, 'Rz': start['Rz']+delta*i/n}
            joints = check_path(pose, goal, joints, self.params, self.envelope)
            goals.append(goal['Rz'])
            pose = goal
        result = dict(ok=True)
        for yaw in goals:
            result = super().rotate_to_rz(yaw)
        return result


def run_original_disk(run, svc, cam, teach, params):
    from sequences import seq_find_disk_legacy
    run.target = None
    guard = OriginalDiskGuard(svc, run, params)
    try:
        guard._preflight()
        telemetry = guard.torque_report()
        number(telemetry.get('e1_position'), 'E1 position')
        if number(telemetry.get('e1_torque'), 'E1 torque') <= -100:
            raise TransferError('gripper may be holding an object; empty jaws required')
        run.say('ORIGINAL TWO-CIRCLE CALIBRATION: vendor teach loop and Z refinement. '
                'Current path/arrival guards retained; motion speed capped at 5. '
                'Review residuals: the original loop may return a last-good estimate, not convergence.')
        result = seq_find_disk_legacy(run, guard, cam, teach)
        if not result.get('ok'):
            run.target = None
        elif run.target:
            run.target.update(source='original_two_circle', alignment_requires_preflight=True)
        return result
    except Exception as ex:
        run.target = None
        run.state = 'stopped' if run.stopped() else 'error'
        run.say(str(ex), 'err')
        return dict(ok=False, error=str(ex))
