"""Open the offline S4 test cell in MuJoCo's persistent interactive viewer."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from contact_sim import build_model, contact_names
from measured_scene import measured_scene


def load_project():
    scene = measured_scene()
    model, xml = build_model(scene)
    data = mujoco.MjData(model)
    names = ['J1', 'J2', 'J3', 'J4', 'finger_-1', 'finger_1']
    targets = [.15, *np.deg2rad([-45, 90, 0]), .014, .014]
    for name, value in zip(names, targets):
        data.qpos[model.joint(name).qposadr[0]] = value
    data.ctrl[:] = targets
    mujoco.mj_forward(model, data)
    if any(c.dist < -.001 for c in data.contact):
        raise ValueError('Initial overlap: ' + str(contact_names(model, data)))
    root = ET.fromstring(xml)
    ET.SubElement(root.find('visual'), 'headlight', ambient='.4 .4 .4', diffuse='.7 .7 .7', specular='.15 .15 .15')
    root.find('visual/global').set('azimuth', '0')
    root.find('visual/global').set('elevation', '-45')
    ET.SubElement(root, 'statistic', center='.34 .02 .20', extent='.85')
    ET.SubElement(ET.SubElement(root, 'keyframe'), 'key', name='start_open',
                  qpos=' '.join(map(str, data.qpos)), ctrl=' '.join(map(str, data.ctrl)))
    xml = ET.tostring(root, encoding='unicode')
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    return model, data, xml, scene


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without opening a window')
    parser.add_argument('--render', action='store_true', help='Save measured scene and review images without opening a window')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'runs'/'interactive')
    args = parser.parse_args()
    model, data, xml, scene = load_project()
    if args.check:
        for _ in range(1000):
            mujoco.mj_step(model, data)
        assert np.isfinite(data.qpos).all()
        assert not any(w.number for w in data.warning)
        print('PROJECT CHECK PASSED: 2 seconds of stable offline physics; '+str(contact_names(model, data)))
    else:
        output = args.output
        output.mkdir(parents=True, exist_ok=True)
        (output/'scene.xml').write_text(xml, encoding='utf-8')
        (output/'scene_config.json').write_text(json.dumps(scene, indent=2), encoding='utf-8')
        if args.render:
            from PIL import Image
            camera=mujoco.MjvCamera()
            camera.lookat[:]=[.34,.02,.17]
            camera.distance=1.2
            camera.azimuth=55
            camera.elevation=-35
            with mujoco.Renderer(model,height=600,width=800) as renderer:
                renderer.update_scene(data,camera=camera)
                Image.fromarray(renderer.render()).save(output/'layout_perspective.png')
                camera.lookat[:]=[.34,.02,0]
                camera.azimuth=0
                camera.elevation=-90
                camera.orthographic=1
                renderer.update_scene(data,camera=camera)
                Image.fromarray(renderer.render()).save(output/'layout_top.png')
            print('Saved measured scene and renders to '+str(output))
        else:
            from mujoco import viewer
            print('Measured workcell layout; simulated actuators only. See workcell_dimensions.json for remaining estimates.', flush=True)
            viewer.launch(model, data)
