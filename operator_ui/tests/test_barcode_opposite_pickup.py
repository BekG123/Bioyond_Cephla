import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import barcode_opposite_pickup as m

class PickupTests(unittest.TestCase):
    def test_failed_closure_stops_without_lift_or_retry(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'run.json';source.write_text('{}')
            pose=dict(X=313.03,Y=-65.92,Z=75.72,Rz=90.07)
            g=dict(seat=pose,cfg={})
            s=dict(robot=dict(connected=True,errors=[],enabled=True,control_mode={'mode':'auto'},
                program_state={'state':'running'},lua_app_initialized=True,pose_mm=pose,joints={}),
                sequence={'active':False},envelope=dict(enabled=True,**{k:dict(min=v[0],max=v[1]) for k,v in
                {'X':[200,450],'Y':[-250,380],'Z':[70,400]}.items()}))
            calls=[]
            def api(path,body=None):
                calls.append((path,body))
                if path=='state':return s
                if path=='researcher/api/lacry/state':return {}
                if path=='robot_params':return {}
                if path=='gripper':return dict(ok=False,error='timeout')
                if path=='program':return dict(ok=True)
                raise AssertionError(path)
            rpc=Mock();rpc.info.return_value=dict(moving=False,error=False,emergency=False,drag=False,manual=False,
                external_axes={'E1':28,'E2':181.77})
            with patch.object(m,'source_data',return_value=(source,{'plan':{'target':181.77}},g)),patch.object(m,'api',side_effect=api),\
                 patch.object(m,'DragGoRPC',return_value=rpc),patch.object(m,'check_path'):
                with self.assertRaisesRegex(RuntimeError,'no retry'):m.run(source,True)
            self.assertEqual(sum(p=='gripper' for p,b in calls),1)
            self.assertFalse(any(p=='move' for p,b in calls))
            self.assertEqual(sum(p=='program' for p,b in calls),1)
            self.assertEqual(json.loads(source.with_name('pickup.json').read_text())['status'],'stopped_or_uncertain')

    def test_observation_required(self):
        with patch.object(m,'api') as api:
            with self.assertRaisesRegex(RuntimeError,'centering observation'):m.run('none')
            api.assert_not_called()

if __name__=='__main__':unittest.main()
