import unittest
from copy import deepcopy
from autonomy import TransferError
from cellvis24_rack_route import reference,validate_route,validate_shape,validate_speeds,PROFILES
from trajectory_queue import LuaTrajectory
from test_short_side_hover_transfer import HoverTransferTests

class LoadedRackTests(unittest.TestCase):
    def test_both_loaded_connectors_and_real_queue_dispatch(self):
        p=reference();env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        self.assertEqual(p['routes']['forward']['start']['Z'],81.37)
        self.assertEqual(p['routes']['forward']['points'][3]['Z'],77)
        for name,profile in zip(('forward','reverse'),PROFILES):
            r=p['routes'][name]
            validate_route(r['start'],r['points'],r['start_joints'],p['config'],env,profile)
            helper=HoverTransferTests();helper.setup_route();s=helper.s
            s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints']);s.envelope=env
            result=LuaTrajectory(s).execute(helper.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
                    reviewed=True,hamilton_short_side=profile,segment_speeds=r['segment_speeds'])
            self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
            self.assertEqual([c[1] for c in s.robot.calls],r['segment_speeds'])
            self.assertEqual(s.grips,[])

    def test_empty_start_or_changed_route_or_contact_speed_rejected(self):
        r=reference()['routes']['forward'];profile=PROFILES[0]
        with self.assertRaises(TransferError):validate_shape(dict(r['start'],Z=106.37),r['points'],profile)
        points=deepcopy(r['points']);points[3]['Z']=139.93
        with self.assertRaises(TransferError):validate_shape(r['start'],points,profile)
        with self.assertRaises(TransferError):validate_speeds(r['start'],r['points'],profile,[137]*len(r['points']))

    def test_reaches_taught_clearance_before_turning(self):
        p=reference();r=p['routes']['forward'];points=r['points']
        self.assertEqual(points[0]['Rz'],r['start']['Rz'])
        self.assertEqual(points[1],p['taught_pivot'])
        for point in points[:3]:
            self.assertEqual([point[k] for k in ('X','Y','Z')],[236.19,-56.22,110.65])
        self.assertLess(points[1]['Rz'],points[0]['Rz'])
        self.assertLess(points[2]['Rz'],points[1]['Rz'])
        self.assertEqual(points[-1],dict(X=372.43,Y=-186.67,Z=53.72,Rz=-93.02))
        self.assertEqual(p['routes']['reverse']['points'],list(reversed([r['start']]+points))[1:])
        for name in ('forward','reverse'):
            self.assertTrue(p['routes'][name]['validation']['workspace_valid'])

if __name__=='__main__':unittest.main()
