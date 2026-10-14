"""Verify exterior geometry and edge clearances, independent of camera view."""
import unittest
import mujoco
import numpy as np
from contact_sim import build_model, contact_names
from measured_scene import measured_scene
from open_project import load_project


class MeasuredSceneTests(unittest.TestCase):
    def test_rack_bounds_and_pitch(self):
        model,_=build_model(measured_scene())
        rack=model.body('rack').id
        ids=np.flatnonzero(model.geom_bodyid==rack)
        lower=np.min(model.geom_pos[ids]-model.geom_size[ids],axis=0)
        upper=np.max(model.geom_pos[ids]+model.geom_size[ids],axis=0)
        np.testing.assert_allclose((upper-lower)*1000,[107.95,139.7,406.4],atol=1e-7)
        surfaces=[(model.geom_pos[model.geom('shelf_'+str(i)).id,2]+model.geom_size[model.geom('shelf_'+str(i)).id,2])*1000 for i in range(1,6)]
        np.testing.assert_allclose(np.diff(surfaces),[88.9]*4,atol=1e-7)

    def test_plate_orientation_and_edge_gaps(self):
        scene=measured_scene();model,_=build_model(scene);data=mujoco.MjData(model)
        mujoco.mj_forward(model,data)
        rack=model.body('rack').id;plate=model.body('plate').id
        rotation=data.xmat[rack].reshape(3,3)
        local=rotation.T@(data.xpos[plate]-data.xpos[rack])
        plate_rotation=rotation.T@data.xmat[plate].reshape(3,3)
        # Long plate axis must follow rack width, not rack depth.
        np.testing.assert_allclose(plate_rotation,np.eye(3),atol=1e-8)
        pg=model.geom('plate_geom').id;bg=model.geom('rack_base').id
        extent=np.abs(plate_rotation)@model.geom_size[pg]
        self.assertLess(local[0],0, 'Calibration plate must be left when facing the rack')
        self.assertGreater(data.xpos[plate,1],scene['robot']['base_y_mm']/1000)
        left_gap=-local[0]-extent[0]-model.geom_size[bg,0]
        toward_gap=-local[1]-extent[1]-model.geom_size[bg,1]
        np.testing.assert_allclose([left_gap,toward_gap],[.1397,.1524],atol=1e-8)

    def test_scene_settles_without_obstruction(self):
        model,data,_,_=load_project()
        for _ in range(1000):mujoco.mj_step(model,data)
        self.assertTrue(np.isfinite(data.qpos).all())
        self.assertFalse(any(w.number for w in data.warning))
        pairs=contact_names(model,data)
        self.assertTrue(pairs)
        self.assertTrue(all(set(pair)=={'plate_geom','support_top'} for pair in pairs),pairs)


if __name__=='__main__':unittest.main()
