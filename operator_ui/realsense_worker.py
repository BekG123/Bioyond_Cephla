"""Local D405 capture and mjviser/Viser display. Never connects to the arm.

Single camera owner; explicit start/release. No camera is opened on import/startup.
Full-resolution raw depth is retained; only the interactive cloud is thinned.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import json
from pathlib import Path
import threading
import time
import uuid

import cv2
from flask import Flask, Response, jsonify, request
import mujoco
from mjviser import ViserMujocoScene
import numpy as np
import pyrealsense2 as rs
import viser
from waitress import serve

from realsense_processing import depth_preview, jpeg, ply_bytes, sample_frame, select_cloud

ROOT = Path(__file__).resolve().parents[1]


def intrinsics_dict(profile):
    i = profile.as_video_stream_profile().get_intrinsics()
    return dict(width=i.width, height=i.height, fx=i.fx, fy=i.fy, ppx=i.ppx, ppy=i.ppy,
                distortion=str(i.model), coefficients=list(i.coeffs))


class DepthView:
    def __init__(self, viser_port=8086, captures=None):
        self.lock = threading.RLock()
        self.transition = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.frame = None
        self.state = 'idle'
        self.error = ''
        self.mode = None
        self.device = None
        self.frame_count = 0
        self.fps = 0.
        self.captures = Path(captures or ROOT/'operator_ui/realsense_captures')
        self.server = viser.ViserServer(host='127.0.0.1', port=viser_port)
        self.server.gui.configure_theme(dark_mode=True,show_share_button=False,brand_color=(45,170,185))
        self.viser_port = self.server.get_port()
        # Schematic camera marker rendered through the cloned mjviser package.
        # It is in the optical frame, not a calibrated model of the robot/tool.
        model = mujoco.MjModel.from_xml_string('''<mujoco><worldbody>
          <body name="camera_origin_marker"><geom type="box" size=".02 .015 .008"
            pos="0 0 -.01" rgba=".25 .3 .4 1"/><geom type="sphere" size=".003"
            pos="-.009 0 0" rgba=".1 .6 1 1"/><geom type="sphere" size=".003"
            pos=".009 0 0" rgba=".1 .6 1 1"/></body></worldbody></mujoco>''')
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        self.mjscene = ViserMujocoScene(self.server, model, num_envs=1)
        self.mjscene.update_from_mjdata(data)
        self.server.scene.set_up_direction('-y')
        self.server.scene.add_frame('/optical_origin', axes_length=.04, axes_radius=.001)
        self.cloud = self.server.scene.add_point_cloud('/depth', points=np.zeros((1,3), np.float32),
            colors=np.zeros((1,3), np.uint8), point_size=.0015, visible=False)
        self.server.scene.add_label('/origin_label', text='Camera optical origin (schematic)', position=(0,-.03,0))
        self.note = self.server.gui.add_markdown('**Idle — connect the D405, then press Start D405 in the console.**')
        with self.server.gui.add_folder('Depth display'):
            self.near = self.server.gui.add_slider('Near (m)', min=.01, max=.5, step=.01, initial_value=.02)
            self.far = self.server.gui.add_slider('Far (m)', min=.05, max=2., step=.01, initial_value=1.)
            self.stride = self.server.gui.add_dropdown('Point density', options=('Full','1/2','1/4','1/8'), initial_value='1/4')
            self.color_mode = self.server.gui.add_dropdown('Color', options=('RGB','Depth'), initial_value='RGB')
        @self.server.on_client_connect
        def connected(client):
            client.camera.position = (0., -.18, -.30)
            client.camera.look_at = (0., 0., .25)
            client.camera.up_direction = (0., -1., 0.)

    def status(self):
        with self.lock:
            frame = self.frame
            age = time.time()-frame['ts'] if frame else None
            streaming = self.state in ('streaming','demo') and age is not None and age < 2
            return dict(ok=True, service='bioyond-realsense', state=self.state,
                error=self.error, mode=self.mode, device=self.device, streaming=streaming,
                frame_age_s=round(age,2) if age is not None else None,
                frames=self.frame_count, fps=round(self.fps,1),
                resolution=list(frame['depth_m'].shape[::-1]) if frame else None,
                valid_depth_percent=round(float(np.mean(frame['depth_m']>0)*100),1) if frame else None,
                points=len(frame['points']) if frame else 0,
                center_depth_mm=self._center(frame),
                frame='camera optical: X right, Y down, Z forward', units='meters',
                robot_registration='not calibrated', viser_port=self.viser_port,
                versions={n:importlib.metadata.version(n) for n in ('pyrealsense2','viser','mjviser','mujoco')})

    @staticmethod
    def _center(frame):
        if frame is None: return None
        depth = frame['depth_m']; h,w = depth.shape
        v = depth[h//2-2:h//2+3,w//2-2:w//2+3]
        v = v[np.isfinite(v) & (v>0)]
        return round(float(np.median(v)*1000),2) if len(v) else None

    def _state(self, state, error=''):
        with self.lock:
            self.state, self.error = state, error
        self.note.content = f'**{state.upper()}** — {error}'

    def start(self, mode='camera'):
        if mode not in ('camera','demo'): raise ValueError('Mode must be camera or demo')
        with self.transition:
            self._stop()
            self.stop_event.clear()
            with self.lock:
                self.mode = mode; self.frame = None; self.device = None; self.frame_count = 0
            self._state('starting')
            self.thread = threading.Thread(target=self._loop, args=(mode,), daemon=True)
            self.thread.start()

    def _stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=8)
            if self.thread.is_alive():
                raise RuntimeError('Capture is still stopping; do not open a second camera owner')
        self.thread = None
        with self.lock:
            self.frame = None; self.device = None; self.fps = 0
        self.cloud.visible = False
        self._state('idle')

    def stop(self):
        with self.transition: self._stop()

    def _loop(self, mode):
        if mode == 'demo':
            while not self.stop_event.is_set():
                depth, xyz, uv, rgb = sample_frame()
                self._publish(depth, xyz, uv, rgb, dict(source='synthetic', depth_scale_m=.0001), (depth/.0001).astype(np.uint16))
                self.stop_event.wait(.1)
            return
        while not self.stop_event.is_set():
            pipeline = None
            try:
                context = rs.context()
                devices = [d for d in context.query_devices() if 'D405' in d.get_info(rs.camera_info.name)]
                if not devices:
                    self._state('waiting', 'No D405 detected. Connect USB 3 and close other camera viewers.')
                    self.stop_event.wait(2)
                    continue
                if len(devices) != 1:
                    raise RuntimeError('Multiple D405 cameras detected; connect only the intended camera')
                device = devices[0]
                serial = device.get_info(rs.camera_info.serial_number)
                config = rs.config(); config.enable_device(serial)
                config.enable_stream(rs.stream.depth, 640,480,rs.format.z16,30)
                config.enable_stream(rs.stream.color, 640,480,rs.format.rgb8,30)
                pipeline = rs.pipeline(context)
                profile = pipeline.start(config)
                scale = profile.get_device().first_depth_sensor().get_depth_scale()
                dp = profile.get_stream(rs.stream.depth); cp = profile.get_stream(rs.stream.color)
                extr = dp.get_extrinsics_to(cp)
                metadata = dict(source='D405', serial=serial, depth_scale_m=scale,
                    depth_intrinsics=intrinsics_dict(dp), color_intrinsics=intrinsics_dict(cp),
                    depth_to_color=dict(rotation=list(extr.rotation), translation_m=list(extr.translation)))
                with self.lock:
                    self.device = dict(name=device.get_info(rs.camera_info.name), serial=serial,
                        firmware=device.get_info(rs.camera_info.firmware_version),
                        usb=device.get_info(rs.camera_info.usb_type_descriptor) if device.supports(rs.camera_info.usb_type_descriptor) else 'unknown')
                pointcloud = rs.pointcloud()
                while not self.stop_event.is_set():
                    frames = pipeline.wait_for_frames(1500)
                    depth_frame, color_frame = frames.get_depth_frame(), frames.get_color_frame()
                    if not depth_frame or not color_frame: continue
                    raw = np.asanyarray(depth_frame.get_data()).copy()
                    rgb = np.asanyarray(color_frame.get_data()).copy()
                    pointcloud.map_to(color_frame)
                    points = pointcloud.calculate(depth_frame)
                    xyz = np.asanyarray(points.get_vertices()).view(np.float32).reshape(-1,3).copy()
                    uv = np.asanyarray(points.get_texture_coordinates()).view(np.float32).reshape(-1,2).copy()
                    meta = dict(metadata, frame_number=depth_frame.get_frame_number(),
                        device_timestamp_ms=depth_frame.get_timestamp(), timestamp_domain=str(depth_frame.get_frame_timestamp_domain()))
                    self._publish(raw.astype(np.float32)*scale, xyz, uv, rgb, meta, raw)
            except Exception as ex:
                self.cloud.visible = False
                with self.lock: self.frame = None; self.device = None; self.fps = 0
                self._state('waiting', str(ex))
            finally:
                if pipeline is not None:
                    try: pipeline.stop()
                    except RuntimeError: pass
            self.stop_event.wait(2)

    def _publish(self, depth, xyz, uv, rgb, metadata, raw):
        near, far = float(self.near.value), float(self.far.value)
        far = max(near+.01, far)
        stride = {'Full':1,'1/2':2,'1/4':4,'1/8':8}[self.stride.value]
        points, colors = select_cloud(xyz, uv, rgb, near, far, stride)
        if self.color_mode.value == 'Depth' and len(points):
            colors = depth_preview(points[:,2].reshape(1,-1), near, far).reshape(-1,3)
        now = time.time()
        with self.server.atomic():
            self.cloud.points = points; self.cloud.colors = colors
            self.cloud.visible = len(points)>0
        with self.lock:
            previous = self.frame['ts'] if self.frame else now
            self.fps = 1/max(.001,now-previous) if self.frame else 0
            self.frame_count += 1
            self.frame = dict(ts=now, depth_m=depth, raw=raw, rgb=rgb, xyz=xyz, uv=uv,
                points=points, colors=colors, metadata=dict(metadata, host_timestamp=now,
                    point_frame='camera optical X right Y down Z forward', units='meters'),
                color_jpeg=jpeg(rgb), depth_jpeg=jpeg(depth_preview(depth,near,far)))
        self._state('demo' if self.mode == 'demo' else 'streaming',
            'SYNTHETIC SAMPLE — no camera observation' if self.mode == 'demo' else 'Measured D405 depth in camera coordinates')

    def fresh_frame(self):
        with self.lock:
            if self.frame is None or time.time()-self.frame['ts']>2:
                raise ValueError('No fresh depth frame; start the D405 or sample view')
            return self.frame

    def export_cloud(self):
        f = self.fresh_frame()
        # Export all positive valid depths, independent of display range/density.
        points, colors = select_cloud(f['xyz'],f['uv'],f['rgb'],1e-6,float('inf'),1)
        return ply_bytes(points, colors)

    def snapshot(self):
        f = self.fresh_frame()
        folder = self.captures/(time.strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        np.save(folder/'depth_m.npy',f['depth_m'])
        if not cv2.imwrite(str(folder/'depth_raw.png'),f['raw']): raise RuntimeError('Could not save raw depth')
        if not cv2.imwrite(str(folder/'color.png'),cv2.cvtColor(f['rgb'],cv2.COLOR_RGB2BGR)): raise RuntimeError('Could not save color')
        points, colors = select_cloud(f['xyz'],f['uv'],f['rgb'],1e-6,float('inf'),1)
        (folder/'cloud_m.ply').write_bytes(ply_bytes(points,colors))
        (folder/'metadata.json').write_text(json.dumps(f['metadata'],indent=2),encoding='utf-8')
        return dict(ok=True,path=str(folder),source=f['metadata']['source'])


def make_app(view):
    app = Flask(__name__)
    @app.get('/status')
    def status(): return jsonify(view.status())
    @app.post('/start')
    def start():
        try: view.start((request.get_json(silent=True) or {}).get('mode','camera')); return jsonify(view.status())
        except (ValueError,RuntimeError) as ex: return jsonify(ok=False,error=str(ex)),400
    @app.post('/stop')
    def stop():
        try: view.stop(); return jsonify(view.status())
        except RuntimeError as ex: return jsonify(ok=False,error=str(ex)),409
    @app.get('/image/<kind>')
    def image(kind):
        if kind not in ('color','depth'): return jsonify(ok=False,error='Unknown image'),404
        try: return Response(view.fresh_frame()[kind+'_jpeg'],mimetype='image/jpeg',headers={'Cache-Control':'no-store'})
        except ValueError as ex: return jsonify(ok=False,error=str(ex)),409
    @app.get('/cloud.ply')
    def cloud():
        try: return Response(view.export_cloud(),mimetype='application/octet-stream')
        except ValueError as ex: return jsonify(ok=False,error=str(ex)),409
    @app.post('/snapshot')
    def snapshot():
        try: return jsonify(view.snapshot())
        except (ValueError,OSError,RuntimeError) as ex: return jsonify(ok=False,error=str(ex)),409
    return app


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=5056)
    p.add_argument('--viser-port',type=int,default=8086)
    a = p.parse_args()
    view = DepthView(a.viser_port)
    try: serve(make_app(view),host='127.0.0.1',port=a.port,threads=4)
    finally: view.stop(); view.server.stop()
