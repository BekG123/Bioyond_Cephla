"""Offline regression checks; no robot services imported."""
import copy
import tempfile
import unittest
from pathlib import Path
import mujoco
import numpy as np
from contact_sim import build_model, default_scene, validate, trajectory, target_at, contact_names, run


def demo():
    a=dict(t=0,J1=150,J2=-45,J3=90,J4=0,e1_mm=28,phase='approach')
    return dict(schema='bioyond-demo-v1',units=dict(distance='mm',angle='deg',time='s'),scene=default_scene(),samples=[a,dict(a,t=1,J1=170,phase='lift')])


class ContactTests(unittest.TestCase):
    def test_validation(self):
        validate(demo())
        for key,value in [('J1',401),('J4',151),('e1_mm',29),('t',0),('J2',float('nan')),('J3',-90)]:
            doc=demo();doc['samples'][1][key]=value
            with self.assertRaises(ValueError):validate(doc)

    def test_retiming(self):
        values,times=trajectory(demo()['samples'])
        np.testing.assert_allclose(target_at(0,values,times)[0],values[0])
        np.testing.assert_allclose(target_at(times[-1]+1,values,times)[0],values[-1])
        ts=np.linspace(0,times[-1],1000)
        z=np.array([target_at(t,values,times)[0][0] for t in ts])
        self.assertLess(np.max(np.abs(np.diff(z)/np.diff(ts))),.03001)

    def test_fk_and_gripper(self):
        model,_=build_model(default_scene());d=mujoco.MjData(model)
        for name,value in [('J1',.15),('J2',np.pi/4),('J3',np.pi/2),('J4',0),('finger_-1',.014),('finger_1',.014)]: d.qpos[model.joint(name).qposadr[0]]=value
        mujoco.mj_forward(model,d)
        np.testing.assert_allclose(d.site_xpos[model.site('tcp').id],[.126+np.sqrt(.08),0,.15],atol=1e-8)
        a=d.geom_xpos[model.geom('jaw_geom_-1').id];b=d.geom_xpos[model.geom('jaw_geom_1').id]
        self.assertAlmostEqual(np.linalg.norm(a-b)-.006,.088)
        for name in ['J1','J2','J3','J4']: self.assertTrue(model.joint(name).limited)

    def test_plate_shelf_contact(self):
        sc=default_scene();model,_=build_model(sc);d=mujoco.MjData(model)
        adr=model.joint('plate_free').qposadr[0]
        d.qpos[adr:adr+3]=[.35,.18,.14]
        # Park arm well clear; plate drops freely onto shelf 2, no weld.
        for n,v in [('J1',.3),('J2',-.5),('J3',1.5)]: d.qpos[model.joint(n).qposadr[0]]=v
        d.ctrl[:4]=[.3,-.5,1.5,0];d.ctrl[4:]=.014
        for _ in range(1000):mujoco.mj_step(model,d)
        self.assertTrue(any('plate_geom' in pair and 'shelf_2' in pair for pair in contact_names(model,d)))
        self.assertAlmostEqual(d.xpos[model.body('plate').id,2],.1172,delta=.001)
        self.assertEqual(model.neq,0)

    def test_rollout(self):
        with tempfile.TemporaryDirectory() as folder:
            report=run(demo(),folder)
            self.assertTrue(report['completed'])
            self.assertTrue((Path(folder)/'final.png').is_file())
            self.assertTrue((Path(folder)/'rollout.npz').is_file())

    def test_initial_overlap_rejected(self):
        doc=demo();doc['samples'][0]['J2']=45
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'penetration'):run(doc,folder)

    def test_friction_grasp_lift_release(self):
        sc=default_scene();sc['plate'].update(x=317.6,y=-277.4127125,yaw_deg=0)
        model,_=build_model(sc);d=mujoco.MjData(model)
        q=[.0272,-np.pi/4,np.pi/2,-np.pi/4,.014,.014]
        adr=[model.joint(n).qposadr[0] for n in ['J1','J2','J3','J4','finger_-1','finger_1']]
        d.qpos[adr]=q;d.ctrl[:]=q
        for _ in range(200):mujoco.mj_step(model,d)
        d.ctrl[4:]=.0115
        for _ in range(400):mujoco.mj_step(model,d)
        pairs=contact_names(model,d)
        self.assertTrue(any('plate_geom' in pair and 'jaw_geom_-1' in pair for pair in pairs))
        self.assertTrue(any('plate_geom' in pair and 'jaw_geom_1' in pair for pair in pairs))
        for _ in range(1000):
            d.ctrl[0]=min(.09,d.ctrl[0]+.00006);mujoco.mj_step(model,d)
        z=d.xpos[model.body('plate').id,2]
        self.assertGreater(z,.07)
        d.ctrl[4:]=.014
        for _ in range(1000):mujoco.mj_step(model,d)
        self.assertLess(d.xpos[model.body('plate').id,2],.04)


if __name__=='__main__':unittest.main()
