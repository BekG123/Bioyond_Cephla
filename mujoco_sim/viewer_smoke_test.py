import time
import mujoco
import mujoco.viewer

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

print("launching passive viewer window for 3 seconds...")
with mujoco.viewer.launch_passive(model, data) as viewer:
    t0 = time.time()
    while viewer.is_running() and time.time() - t0 < 3:
        mujoco.mj_step(model, data)
        viewer.sync()
        time.sleep(model.opt.timestep)
print("VIEWER SMOKE TEST PASSED (window opened and closed without error)")
