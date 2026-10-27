import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import supervised_grip_increment as step


class Tests(unittest.TestCase):
    def test_no_confirmation_never_reads_or_commands(self):
        with patch.object(step, 'api') as api:
            with self.assertRaises(ValueError):
                step.execute('missing', 28., False)
            api.assert_not_called()

    def test_one_step_only_and_plate_record_rejected_as_baseline(self):
        pose = dict(X=309.5, Y=-66., Z=70.46, Rz=89.)
        state = dict(sequence=dict(active=False), robot=dict(connected=True, ok=True,
            errors=[], enabled=True, control_mode=dict(mode='auto'),
            program_state=dict(state='running'), pose_mm=pose, external_axes=dict(E1=28.)))
        commands = []
        def api(path, body=None):
            if path == '/state':
                return state
            if path == '/researcher/api/status':
                return dict(hand_guiding=dict(state='off'))
            if path == '/gripper':
                commands.append(body)
                if body['action'] == 'move':
                    state['robot']['external_axes']['E1'] = body['e1']
                    return dict(ok=True)
                return dict(ok=True, telemetry_live=True, e1_position=27.9, e1_torque=100.)
            self.fail('Unexpected command: '+path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root/'baseline.json'
            data = dict(kind='empty_claw_baseline', ok=True, operator_confirmed_empty=True,
                        start_pose_mm=pose, positions=[])
            baseline.write_text(json.dumps(data))
            with patch.object(step, 'ROOT', root), patch.object(step, 'api', side_effect=api):
                step.execute(baseline, 28., True)
                self.assertEqual([c for c in commands if c['action']=='move'],
                                 [dict(action='move', e1=27.9, speed=5)])
                data['kind'] = 'plate_present_closing_measurement'
                baseline.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'correctly labeled'):
                    step.execute(baseline, 27.9, True)
                self.assertEqual(len(commands), 4)
        state['robot']['pose_mm'] = {**pose, 'Z':75}
        with self.assertRaisesRegex(ValueError, 'Arm moved'):
            step.validate(state, pose)


if __name__ == '__main__':
    unittest.main()
