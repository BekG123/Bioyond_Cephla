"""Offline visual inspection of the generated rack asset, no robot imports."""
from pathlib import Path
import mujoco
from PIL import Image

assets=Path(__file__).resolve().parents[1]/'operator_ui'/'static'/'models'
mesh_data='\n'.join(line for line in (assets/'plate_rack.obj').read_text().splitlines() if not line.startswith('o ')).encode()
xml='''<mujoco><asset><mesh name="rack" file="rack.obj" scale=".001 .001 .001"/></asset>
<visual><global offwidth="700" offheight="800"/></visual>
<worldbody><light pos="0 -1 1" diffuse=".9 .9 .9"/>
<geom type="plane" size="1 1 .01" rgba=".18 .20 .24 1"/>
<geom type="mesh" mesh="rack" rgba=".7 .75 .8 1" contype="0" conaffinity="0"/>
</worldbody></mujoco>'''
m=mujoco.MjModel.from_xml_string(xml,assets={'rack.obj':mesh_data});d=mujoco.MjData(m);mujoco.mj_forward(m,d)
camera=mujoco.MjvCamera();camera.lookat[:]=[0,0,.2];camera.distance=.72;camera.azimuth=-65;camera.elevation=-15
with mujoco.Renderer(m,height=800,width=700) as r:
    r.update_scene(d,camera=camera)
    Image.fromarray(r.render()).save(assets/'plate_rack_preview.png')
print('Rendered rack preview')
