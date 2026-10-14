import mujoco
import numpy as np

XML = """
<mujoco>
  <option gravity="0 0 -9.81"/>
  <worldbody>
    <light name="top" pos="0 0 2"/>
    <geom name="floor" type="plane" size="1 1 0.1" rgba=".9 .9 .9 1"/>
    <body name="box" pos="0 0 0.5">
      <freejoint/>
      <geom name="box_geom" type="box" size="0.05 0.05 0.05" rgba="0.8 0.2 0.2 1"/>
    </body>
  </worldbody>
</mujoco>
"""

model = mujoco.MjModel.from_xml_string(XML)
data = mujoco.MjData(model)

print(f"mujoco version: {mujoco.__version__}")
print(f"nq={model.nq} nv={model.nv} nbody={model.nbody}")

mujoco.mj_forward(model, data)
z0 = data.xpos[model.body("box").id, 2]
for _ in range(200):
    mujoco.mj_step(model, data)
z1 = data.xpos[model.body("box").id, 2]
print(f"box z before={z0:.4f} after 200 steps={z1:.4f} (should have fallen)")
assert z1 < z0, "physics step did not move the body"

renderer = mujoco.Renderer(model, height=240, width=320)
renderer.update_scene(data)
pixels = renderer.render()
print(f"rendered frame shape={pixels.shape}, mean pixel value={pixels.mean():.2f}")
assert pixels.shape == (240, 320, 3)
assert pixels.std() > 0, "rendered frame looks blank"

print("SMOKE TEST PASSED")
