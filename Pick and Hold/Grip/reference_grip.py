"""Staged E1 position closure from accepted evidence; no force-limit writes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from researcher_teaching import TeachingError
from autonomy import TransferError
from .position import PositionGrip
from .fast_position_plan import plan_closure

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(__file__).with_name('accepted_grip_reference.json')
PROFILE = Path(__file__).with_name('fast_position_profile.json')
DESCENT = ROOT/'Pick and Hold/Descend/corrected_endpoint.json'


def plan_for_reference(reference):
    plan = plan_closure(28)
    if reference.get('accepted_plate_grip'):
        if (reference.get('plate_profile_id') != '48_well_projected_20261026'
                or reference['settings']['target_e1_mm'] != 3.9
                or reference['settings']['closing_speed'] != 5
                or reference.get('physical_grip_validated_for_plate') is not True):
            raise TeachingError('Invalid accepted plate grip settings.')
        commands = [step for step in plan['commands'] if step['target_e1_mm'] >= 3.9]
        if not commands or commands[-1]['target_e1_mm'] != 3.9:
            raise TeachingError('Reviewed closure does not contain the accepted 3.9 mm stop.')
        plan.update(target_e1_mm=3.9,commands=commands,command_count=len(commands),
                    validation_status='operator_accepted_48well_grip')
    return plan


def configuration():
    files = [REFERENCE, PROFILE, DESCENT]
    try:
        reference, profile, descent = [json.loads(p.read_bytes()) for p in files]
        if (profile.get('live_enabled') is not True
                or reference['settings']['target_e1_mm'] != 3.8
                or reference['settings']['closing_speed'] != 5
                or reference['status'] != 'operator_accepted_supervised_closure_and_loaded_home_transfer'):
            raise ValueError('Unreviewed grip reference.')
        for item in reference['evidence']:
            path = (ROOT/item['path']).resolve()
            if ROOT not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Grip evidence changed.')
        PositionGrip._pose_matches(descent['endpoint'], reference['closure']['pose_mm_degrees'])
        plan_closure(28)  # Also checks fixed step limits and speed.
        if profile['target_e1_mm'] == 3.7 and profile.get('accepted_sequence'):
            accepted_path = (ROOT/profile['accepted_sequence']).resolve()
            if ROOT not in accepted_path.parents:
                raise ValueError('Invalid accepted sequence path.')
            accepted = json.loads(accepted_path.read_bytes())
            if (accepted.get('status') != 'operator_accepted_successful_sequence'
                    or accepted.get('physical_pickup_success') is not True
                    or accepted.get('plate_retained_during_lift_and_home_operator_confirmed') is not True
                    or accepted['settings']['grip_target_e1_mm'] != 3.7
                    or accepted['settings']['grip_speed'] != 5):
                raise ValueError('Accepted 3.7 mm pickup reference is unavailable.')
            PositionGrip._pose_matches(descent['endpoint'],accepted['settings']['pickup_pose_mm_degrees'])
            files.append(accepted_path)
        elif profile['target_e1_mm'] == 3.7:
            trial_path = (ROOT/profile['trial_authorization']).resolve()
            if ROOT not in trial_path.parents:
                raise ValueError('Invalid supervised trial path.')
            trial = json.loads(trial_path.read_bytes())
            if (trial.get('id') != 'e1_3p7_20261020'
                    or trial.get('status') != 'authorized_supervised_trial'
                    or trial.get('target_e1_mm') != 3.7
                    or trial.get('force_limits_changed') is not False):
                raise ValueError('3.7 mm trial authorization is unavailable.')
            files.append(trial_path)
        digest = hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()
        return reference, digest
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TeachingError('Accepted Grip reference or descent settings need review: '+str(error)) from error


class ReferenceGrip(PositionGrip):
    def __init__(self, folder, service, runner):
        super().__init__(folder, service, runner)
        self.message = 'After Descent, close to the configured setting and inspect before lifting.'
        self.plate_configuration = None

    def _configuration(self, context=None):
        reference,digest=configuration()
        result=(context or {}).get('descent_result',context or {})
        if result.get('plate_profile_id'):
            if self.plate_configuration is None:
                raise TeachingError('Plate-specific grip configuration is unavailable.')
            try:
                return self.plate_configuration(context,reference,digest)
            except (TransferError,OSError,ValueError,KeyError) as error:
                raise TeachingError('Plate-specific Grip is not ready: '+str(error)) from error
        return reference,digest

    def configuration_ready(self):
        configuration()

    def completed_descent(self, result, pose):
        reference, digest = self._configuration(result)
        self._pose_matches(pose, reference['closure']['pose_mm_degrees'])
        super().completed_descent(result, pose)
        with self.lock:
            self.receipt['grip_reference_sha256'] = digest
            self._save_receipt()

    def _ready(self, robot):
        super()._ready(robot)
        reference, digest = self._configuration(self.receipt)
        if self.receipt.get('grip_reference_sha256') != digest:
            raise TeachingError('Grip configuration changed since Descent; run Descent again.')
        self._pose_matches(robot['pose_mm'], reference['closure']['pose_mm_degrees'])

    def public(self, robot):
        state = super().public(robot)
        state.update(method='staged_reference_position', supervised_validation=True,
                     force_control=False, increment_phases_mm=[1, .2, .1])
        try:
            reference,_ = self._configuration(self.receipt)
            state['target_e1_mm'] = plan_for_reference(reference)['target_e1_mm']
        except (OSError, ValueError, KeyError, TypeError, TeachingError):
            state['target_e1_mm'] = None
        return state

    def execute(self, run, receipt):
        svc = self.service()
        record = dict(id=uuid4().hex, at=time.time(), method='staged_reference_position',
                      descent=deepcopy(receipt), speed=5,
                      steps=[], grasp_verified=False, contact_detected=False,
                      force_limits_changed=False)
        path = self.folder/(record['id']+'.json')
        sent = False

        def save():
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

        def check():
            if run.stopped():
                raise TeachingError('Grip stopped; no next increment.')
            refusal = svc._preflight()
            if refusal:
                raise TeachingError(refusal)
            self._pose_matches(svc.pose_mm(), receipt['pose_mm'])

        try:
            reference, digest = self._configuration(receipt)
            if receipt.get('grip_reference_sha256') != digest:
                raise TeachingError('Grip settings changed after Descent.')
            self._pose_matches(receipt['pose_mm'], reference['closure']['pose_mm_degrees'])
            check()
            opening = self._number(svc.external_axes().get('E1'))
            if not 27.98 <= opening <= 28.05:
                raise TeachingError('Grip requires the fully open claw from Descent.')
            # Normalize encoder tolerance; the commands are the reviewed 28 mm plan.
            plan = plan_for_reference(reference)
            final_target = plan['target_e1_mm']
            planned = plan['commands']
            record.update(reference_sha256=digest, opening_mm=opening, plan=planned,
                          target_e1_mm=final_target)
            save()
            if final_target == 3.7 and not json.loads(PROFILE.read_bytes()).get('accepted_sequence'):
                # One commissioned attempt only. Failed attempts also consume it.
                # No restart or subsequent Full Calibration may reuse this trial.
                profile = json.loads(PROFILE.read_bytes())
                profile.update(live_enabled=False, status='supervised_3p7_attempt_consumed',
                               attempted_record=str(path))
                temporary = PROFILE.with_suffix('.tmp')
                temporary.write_text(json.dumps(profile, indent=2), encoding='utf-8')
                temporary.replace(PROFILE)
            previous = opening
            for index, step in enumerate(planned, 1):
                check()
                if abs(self._number(svc.external_axes().get('E1'))-previous) > .05:
                    raise TeachingError('Claw moved between increments.')
                target = step['target_e1_mm']
                item = dict(command=step, started_at=time.time())
                record['steps'].append(item)
                save()
                sent = True
                response = svc.move_gripper(target, speed=5)
                item['response'] = response
                save()
                if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                    raise TeachingError('Uncertain Grip increment; no retry.')
                deadline = time.monotonic()+self.SETTLE_TIMEOUT
                stable = 0
                while stable < self.SETTLE_SAMPLES:
                    check()
                    actual = self._number(svc.external_axes().get('E1'))
                    if time.monotonic() > deadline:
                        raise TeachingError('Grip increment did not settle; no further closure.')
                    stable = stable+1 if abs(actual-target) <= .02 else 0
                    if stable < self.SETTLE_SAMPLES:
                        time.sleep(self.SETTLE_INTERVAL)
                report = svc.torque_report()
                item.update(settled_e1_mm=actual, stationary_report=report)
                save()
                if (report.get('ok') is not True or report.get('telemetry_live') is not True
                        or report.get('recovered')
                        or abs(self._number(report.get('e1_position'))-target) > .05):
                    raise TeachingError('Fresh grip feedback was not confirmed.')
                self._number(report.get('e1_torque'))
                check()
                previous = actual
                run.audit('reference_grip_step', index=index, total=len(planned), **item)
                run.say(f'Grip {index}/{len(planned)}: E1 {actual:.3f} mm.')
            # Observe delayed faults without further movement.
            end = time.monotonic()+2
            while time.monotonic() < end:
                check()
                if abs(self._number(svc.external_axes().get('E1'))-final_target) > .05:
                    raise TeachingError('Claw moved after closing.')
                time.sleep(.1)
            record.update(ok=True, measured_e1_mm=svc.external_axes()['E1'],
                          pose_mm=svc.pose_mm(), elapsed_s=time.time()-record['at'])
            save()
            self.message = f'Grip reached {final_target:.1f} mm. Inspect the plate before lifting.'
            run.audit('reference_grip_complete', record=record)
            return dict(ok=True, executor='staged_reference_position', e1_position=record['measured_e1_mm'],
                        target_e1_mm=final_target, gripped=False, grasp_verified=False,
                        awaiting_inspection=True, record=str(path))
        except Exception as error:
            record.update(ok=False, error=str(error))
            if sent:
                try:
                    record['stop_response'] = svc.program('stop')
                except Exception as stop_error:
                    record['stop_error'] = str(stop_error)
            try:
                save()
            except (OSError, ValueError):
                pass
            self.message = 'Grip stopped. Inspect the plate and Developer details.'
            run.say(str(error), 'err')
            return dict(ok=False, error=str(error), grasp_verified=False, record=str(path))
