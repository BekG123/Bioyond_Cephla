"""Offline real-teaching UI QA with a fake read-only robot and temporary store."""
import asyncio
import base64
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server
import websockets

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from researcher import register_researcher
from researcher_teaching import StationTeaching
from researcher_teaching import TeachingError
from draggo import DragGo
from hand_claw import HandClaw
from researcher_routine_check import check_routine
from test_draggo import FakeRPC
from researcher_workflow import PlateTeaching
from test_researcher_workflow import FakeRunner

OUTPUT = UI / 'reports/researcher_ui'
app = Flask(__name__, static_folder=str(UI / 'static'))
requests_seen = []
state = dict(offline=False)


class FakeRobot:
    def __init__(self):
        self.robot = self
        self.connected = False
        self.x = 250.
        self.program_state = 'stopped'
        self.program_calls = []
        self._motion = threading.Lock()

    def _endpoint_addr(self):
        return ('offline', 56788)

    def connect(self):
        self.connected = True
        return dict(ok=True)

    def status(self):
        return dict(ok=True, connected=self.connected, errors=[], endpoint='offline-test',
                    control_mode=self.get_ctrl_mode(), enabled=fake_rpc.state['enabled'],
                    program_state={'state':self.program_state})

    def get_ctrl_mode(self):
        return dict(mode='manual' if fake_rpc.state['manual'] else 'auto')

    def set_enable(self, enabled, confirmed):
        assert confirmed
        fake_rpc.state.update(enabled=enabled, disabled=not enabled)
        return dict(ok=True)

    def _preflight(self):
        assert self.get_ctrl_mode()['mode'] == 'auto' and self.program_state == 'running'
        assert fake_rpc.state['enabled'] and not fake_rpc.state['drag']

    def move_gripper(self, target, speed=0):
        self._preflight()
        self.gripper_calls.append((target,speed))
        fake_rpc.state['external_axes']['E1'] = target
        return dict(ok=True)

    gripper_calls = []

    def program(self, action):
        assert action == 'stop'
        self.program_calls.append(action)
        self.program_state = 'stopped'
        return dict(ok=True)

    def pose_mm(self):
        return dict(X=self.x, Y=-10., Z=200., Rz=0.)

    def joints(self):
        return dict(J1=200., J2=self.x / 10, J3=20., J4=30.)

    def get_joint_info(self):
        return dict(external=dict(E1=15.))

    def external_axes(self):
        if state.get('gripper_unavailable'):
            raise TimeoutError('native feedback unavailable')
        return dict(E1=fake_rpc.state['external_axes']['E1'])


robot = FakeRobot()
storage = tempfile.TemporaryDirectory(prefix='cephla_teaching_test_')
teaching = StationTeaching(Path(storage.name) / 'teaching.json', lambda: robot, settle_seconds=0)
fake_rpc = FakeRPC()
fake_rpc.state.update(external_axes={'E1':15.,'E2':-3.},external_units={'E1':'mm','E2':'degrees'})
draggo = DragGo(lambda: robot, Path(storage.name) / 'draggo.json', lambda host: fake_rpc)
fake_runner = FakeRunner()
plate_flow = PlateTeaching(teaching, lambda: fake_runner,
    lambda: type('Camera', (), {'info':lambda self:dict(enabled=True)})(), lambda: draggo,
    lambda *args:dict(ok=True,target=dict(x=250,y=-10,z_calibrated=200,rz=0,converged=True)),
    lambda *args:dict(ok=True))
plate_flow._prepare = lambda *args: draggo.change(False)


def fake_state():
    if state['offline']:
        raise RuntimeError('Internal connection traceback should never reach UI')
    return dict(robot=robot.status(),
                camera=dict(open=False, error='SDK internal error'), sequence=dict(active=fake_runner.active))


class FakeImitation:
    ready = False
    active = False
    descended = False
    action = None
    calls = []
    def public(self, robot):
        return dict(active=self.active, message='Keep hands clear.' if self.active else 'Ready for taught actions.',
            blocker='' if self.ready else 'Add the Haiku key and a reviewed reference in Developer view.',
            reference_id='offline-reviewed-reference', can_descend=self.ready and not self.active and not self.descended,
            can_grip=self.ready and not self.active and self.descended)
    def start(self, action, body):
        assert body == {'reference_id':'offline-reviewed-reference'}
        self.calls.append(action); self.action = action; self.active = True
        return dict(ok=True)
    def stop(self):
        self.calls.append('stop'); self.active = False; self.descended = False
        return dict(ok=True)


fake_imitation = FakeImitation()
class FakeDescent:
    ready=False
    active=False
    calls=[]
    def public(self,robot):
        return dict(active=self.active,can_start=self.ready and not self.active,
                    message='Opening the claw, then descending.' if self.active else 'Run Align, then Descend.',
                    blocker='' if self.ready else 'Run Align before Descend.')
    def start(self,body):
        assert body=={'ready':True}
        self.calls.append('start');self.active=True
        return dict(ok=True)
    def stop(self):
        self.calls.append('stop');self.active=False;self.ready=False
        return dict(ok=True,message='Stop requested.')
fake_descent=FakeDescent()
class FakeGrip:
    ready=False
    active=False
    calls=[]
    def public(self,robot):
        return dict(active=self.active,can_start=self.ready and not self.active,
                    descent_id='test-descent',message='Closing to the plate setting.' if self.active else 'Grip ready.',
                    blocker='' if self.ready else 'Complete Descent before Grip.')
    def start(self,body):
        assert body=={'ready':True,'descent_id':'test-descent'}
        self.calls.append('start');self.active=True;self.ready=False
        return dict(ok=True)
    def stop(self):
        self.calls.append('stop');self.active=False
        return dict(ok=True,message='Stop requested.')
fake_grip=FakeGrip()
class FakeHome:
    active = False
    calls = []
    def public(self, robot_state, hand):
        return dict(can_start=robot_state['connected'] and not self.active, active=self.active,
                    target_id='test-home',message='Return to saved Home',blocker='',
                    can_go_to_area=robot_state['connected'] and not self.active,area_target_id='test-area')
    def start(self, body):
        area=body.get('destination')=='home_area'
        assert body == (dict(ready=True,target_id='test-area',destination='home_area') if area else dict(ready=True,target_id='test-home'))
        self.active = True
        self.calls.append('area' if area else 'start')
        return dict(ok=True,message='Returning Home')
    def stop(self):
        self.active = False
        self.calls.append('stop')
        return dict(ok=True,message='Stop requested')

fake_home = FakeHome()
class FakeRecordedReturn:
    active=False
    queue_available=False
    calls=[]
    def public(self,robot_state):
        return dict(can_start=robot_state['connected'] and not self.active,active=self.active,
            path_id='test-path',direction='to_hamilton',progress=25,message='Recorded return',blocker='',
            queue=dict(available=self.queue_available,message='Controller queue test status'))
    def start(self,body):
        assert body == dict(ready=True,path_id='test-path',direction='to_hamilton',executor='lua_queue' if self.queue_available else 'stepwise')
        self.active=True
        self.calls.append('start')
        return dict(ok=True)
    def stop(self):
        self.active=False
        self.calls.append('stop')
        return dict(ok=True,message='Stop requested')
fake_recorded_return=FakeRecordedReturn()
class FakeLatest:
    active=False
    calls=[]
    def public(self,robot_state):
        return dict(can_start=robot_state['connected'] and not self.active,active=self.active,
            path_id='latest-path',direction='toward_home',speed=137,progress=30,message='Latest route',blocker='')
    def start(self,body):
        assert body == dict(ready=True,path_id='latest-path',direction='toward_home')
        self.active=True; self.calls.append('start')
        return dict(ok=True,message='Latest route requested')
    def stop(self):
        self.active=False; self.calls.append('stop')
        return dict(ok=True,message='Stopped')
fake_latest=FakeLatest()
coactive_test=dict(current={'id':'base'},blocker='',proposals=[],preferences=[],outcomes=[])

@app.get('/developer/api/coactive')
def coactive_status_test():
    return jsonify(ok=True,**coactive_test)

@app.post('/developer/api/coactive/<action>')
def coactive_action_test(action):
    body=request.get_json()
    if action == 'capture':
        assert body['manually_demonstrated'] is True and body['reference_id']=='base'
        coactive_test['proposals']=[dict(id='proposal',action=body['action'],at='test',status='pending',
            note=body['note'],change={'end_z_before':100,'end_z_after':102},reference={'coactive':{'measured_samples':[]}})]
    else:
        assert body==dict(proposal_id='proposal',decision='accept',reviewed_clear_path=True)
        coactive_test['current']={'id':'accepted'};coactive_test['proposals'][0]['status']='accepted'
    return jsonify(ok=True,message='Saved without movement')

@app.get('/coactive-test')
def coactive_page_test():
    return '<link rel="stylesheet" href="/static/researcher.css"><main><article class="card" id="latest-hamilton"></article><article class="card" id="coactive-pickup"></article></main><script src="/static/latest_route.js"></script><script src="/static/coactive_pickup.js"></script>'
class FakePickupPlanner:
    active=False
    calls=[]
    def public(self):
        return dict(configured=True,active=self.active,message='Haiku is reviewing pickup logs.' if self.active else 'Ready to plan pickup.')
    def start(self,ident):
        teaching.export(ident)
        self.calls.append(ident); self.active=True
        return dict(ok=True,message='Pickup proposal requested. No movement requested.')
fake_pickup_planner=FakePickupPlanner()
def prepare_claw(run, service):
    draggo.change(False)
    fake_rpc.state.update(manual=False,enabled=True,disabled=False,drag=False,moving=False)
    robot.program_state = 'running'
    fake_rpc.state['external_axes']['E1'] = 0.

hand_claw = HandClaw(lambda:robot,lambda:fake_runner,lambda:draggo,
                    lambda:dict(claw_gap_min_mm=60.,claw_gap_max_mm=88.), prepare_claw)
register_researcher(app, fake_state, teaching, draggo, plate_flow, fake_imitation, fake_home, hand_claw,
    routine_check=lambda saved:check_routine(saved,json.loads((UI/'robot_params.json').read_text()),
                                           dict(X=(200,450),Y=(-250,100),Z=(70,400)),True),
    pickup_planner=fake_pickup_planner,recorded_return=fake_recorded_return,latest_hamilton=fake_latest,descent=fake_descent,grip=fake_grip)


@app.before_request
def track():
    requests_seen.append((request.method, request.path))


@app.get('/')
@app.get('/researcher')
def index():
    return send_from_directory(UI / 'static', 'researcher.html')


@app.get('/developer')
def developer():
    return send_from_directory(UI / 'static', 'index.html')


async def check(ws_url, url):
    async with websockets.connect(ws_url, max_size=30_000_000) as ws:
        seq = 0
        errors = []

        async def call(method, params=None):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps(dict(id=seq, method=method, params=params or {})))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if message.get('method') == 'Runtime.exceptionThrown':
                    errors.append(message['params'])
                if message.get('id') == seq:
                    if 'error' in message:
                        raise RuntimeError(message['error'])
                    return message.get('result', {})

        async def js(expression):
            result = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            if 'exceptionDetails' in result:
                raise AssertionError(result['exceptionDetails'])
            return result.get('result', {}).get('value')

        async def until(expression, seconds=12):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if await js(expression):
                    return
                await asyncio.sleep(.1)
            raise AssertionError('UI condition failed: ' + expression)

        async def click(ident):
            assert await js(f"!document.getElementById('{ident}').disabled"), ident + ' disabled'
            await js(f"document.getElementById('{ident}').click()")

        async def screenshot(name):
            result = await call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=True))
            (OUTPUT / (name + '.png')).write_bytes(base64.b64decode(result['data']))

        await call('Runtime.enable')
        await call('Page.enable')
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1080, deviceScaleFactor=1, mobile=False))
        await call('Page.navigate', dict(url=url))
        await until("document.getElementById('robot-status')?.textContent === 'Robot disconnected'")
        assert await js("document.getElementById('capture').disabled && document.getElementById('start-run').disabled && document.getElementById('pause').disabled && document.getElementById('stop').disabled")
        assert await js("!document.body.innerText.includes('SDK internal')")
        await screenshot('prepare_desktop')
        state['offline'] = True
        await click('refresh')
        await until("document.getElementById('robot-status').textContent === 'Robot status unavailable'")
        assert await js("!document.body.innerText.includes('traceback')")
        state['offline'] = False
        await click('refresh')
        await until("document.getElementById('robot-status').textContent === 'Robot disconnected'")
        await click('connect')
        await until("document.getElementById('robot-status').textContent === 'Robot connected'")
        assert robot.connected
        assert await js("!document.getElementById('coactive-pickup')")
        await until("document.getElementById('latest-route-start').textContent === 'Return to Home-area'")
        assert await js("document.getElementById('latest-route-start').disabled")
        await click('latest-route-ready')
        await until("!document.getElementById('latest-route-start').disabled")
        await click('latest-route-start')
        await until("!document.getElementById('latest-route-stop').disabled")
        assert await js("!document.getElementById('latest-route-ready').checked")
        await click('latest-route-stop')
        await until("document.getElementById('latest-route-stop').disabled")
        assert fake_latest.calls==['start','stop']
        assert fake_home.calls == []
        assert await js("document.getElementById('return-home').disabled")
        await click('home-ready')
        await click('return-home')
        await until("!document.getElementById('stop-home').disabled")
        assert await js("!document.getElementById('home-ready').checked")
        await click('stop-home')
        await until("document.getElementById('stop-home').disabled")
        assert fake_home.calls == ['start','stop']
        assert await js("document.getElementById('home-to-area').disabled")
        assert await js("document.getElementById('home-to-area').hidden")
        assert fake_home.calls == ['start','stop']
        assert await js("document.getElementById('recorded-return-start').disabled")
        assert await js("document.getElementById('recorded-return-executor').options[1].disabled")
        await click('recorded-return-ready')
        assert await js("document.getElementById('recorded-return-start').textContent === 'Return to Hamilton'")
        await click('recorded-return-start')
        await until("!document.getElementById('recorded-return-stop').disabled")
        assert await js("!document.getElementById('recorded-return-ready').checked")
        await click('recorded-return-stop')
        await until("document.getElementById('recorded-return-stop').disabled")
        assert fake_recorded_return.calls == ['start','stop']
        fake_recorded_return.queue_available=True
        await click('refresh')
        await until("!document.getElementById('recorded-return-executor').options[1].disabled")
        await js("document.getElementById('recorded-return-executor').value='lua_queue'")
        await click('recorded-return-ready')
        await click('recorded-return-start')
        await until("!document.getElementById('recorded-return-stop').disabled")
        assert await js("document.getElementById('recorded-return-executor').disabled")
        await click('recorded-return-stop')
        await until("document.getElementById('recorded-return-stop').disabled")
        assert fake_recorded_return.calls == ['start','stop','start','stop']
        await js("document.querySelector('[data-stage=teach]').click()")
        assert fake_rpc.calls == [], 'Page loading/connecting must not change servo mode'
        robot.program_state = 'running'
        await click('refresh')
        await until("document.getElementById('hand-guiding-status').textContent.includes('stop the idle controller program')")
        assert robot.program_calls == []
        assert await js("document.getElementById('hand-guiding-start').disabled")
        await click('hand-guiding-ready')
        await click('hand-guiding-start')
        await until("document.getElementById('hand-guiding-status').textContent.includes('Hand-guiding is active')")
        assert robot.program_calls == ['stop']
        fake_rpc.state['moving'] = True  # This firmware keeps this flag on in stationary DragGo.
        assert await js("document.getElementById('hand-claw-step').disabled")
        await click('hand-claw-ready')
        assert await js("document.getElementById('hand-claw-step').disabled")
        await click('hand-claw-empty')
        await click('hand-claw-step')
        await until("!document.getElementById('hand-claw-stop').disabled")
        fake_runner.finish()
        await click('refresh')
        await until("document.getElementById('hand-claw-status').textContent.includes('opening complete')")
        assert abs(fake_rpc.state['external_axes']['E1']-.2) < .0001
        assert robot.gripper_calls == [(.2,5)]
        assert not fake_rpc.state['manual'] and not fake_rpc.state['drag']
        await click('hand-claw-ready')
        await click('hand-claw-open')
        await until("!document.getElementById('hand-claw-stop').disabled")
        await click('hand-claw-stop')
        await until("document.getElementById('notice').textContent.includes('The current controller command finishes first')")
        try:
            fake_runner.finish()
            raise AssertionError('Stopped request executed')
        except TeachingError:
            fake_runner.active = False
        await click('refresh')
        await until("document.getElementById('hand-claw-stop').disabled")
        assert abs(fake_rpc.state['external_axes']['E1']-.2) < .0001
        assert robot.gripper_calls == [(.2,5)]
        await click('hand-guiding-ready')
        await click('hand-guiding-start')
        await until("document.getElementById('hand-guiding-status').textContent.includes('is active') && !document.getElementById('hand-guiding-end').disabled")
        fake_rpc.state['moving'] = False
        assert draggo.blocks_motion
        await screenshot('draggo_active_desktop')
        await click('start-teaching')
        await until("!document.getElementById('capture').hidden && !document.getElementById('capture').disabled")
        assert teaching.public()['draft']['waypoints'] == []
        await click('capture')
        await until("document.getElementById('review-steps').children.length === 1 && !document.getElementById('capture').disabled")
        # A browser reload preserves the real draft on the server.
        await call('Page.reload')
        await until("document.getElementById('robot-status')?.textContent === 'Robot connected'")
        await js("document.querySelector('[data-stage=teach]').click()")
        assert await js("document.getElementById('review-steps').children.length === 1 && !document.getElementById('automatic-controls').hidden")
        for name, button in [('Calibrate','run-calibration'),('Align','run-alignment')]:
            assert await js(f"document.getElementById('{button}').disabled")
            await click('automatic-ready')
            await click(button)
            await until("!document.getElementById('stop-automatic').hidden")
            assert fake_runner.active
            if name == 'Calibrate':
                assert fake_rpc.state['drag'] and fake_rpc.state['enabled']
                plate_flow.publish_guidance(dict(mode='automatic',config='Wide',state='moving',message='Correcting plate centering and distance.',
                    checked_at=time.time(),observations=3,moves=2,elapsed_s=5,confirmation=0,
                    metrics=dict(xy_mm=2,z_mm=1,yaw_deg=.1),initial_metrics=dict(xy_mm=10,z_mm=5,yaw_deg=1)))
                await click('refresh')
                await until("document.getElementById('guidance-progress').textContent.includes('2 corrections')")
                assert await js("document.getElementById('stop-automatic').textContent === 'Stop calibration'")
                assert await js("document.getElementById('hand-guiding-end').disabled")
                await screenshot('automatic_calibration_desktop')
            fake_runner.finish()
            await click('refresh')
            await until("document.getElementById('stop-automatic').hidden")
        # Repeat directly from Run without Undo or loss of the earlier attempt.
        await js("document.querySelector('[data-stage=run]').click()")
        for name,button in [('Calibrate','run-calibration-again'),('Align','run-alignment-again')]:
            await click('run-setup-ready')
            await click(button)
            await until("!document.getElementById('imitate-stop').disabled")
            fake_runner.finish()
            await until("!document.getElementById('refresh').disabled")
            await click('refresh')
            await until("!document.getElementById('run-setup-ready').checked")
            await until(f"document.getElementById('stop-automatic').hidden && document.getElementById('review-steps').children.length === {2 if name == 'Calibrate' else 3}")
        assert len(teaching._load()['draft']['history']) == 1
        assert len(teaching._load()['draft']['history'][0]['waypoints']) == 3
        await js("document.querySelector('[data-stage=teach]').click()")
        for station in ('Descend','Grip'):
            await until(f"document.getElementById('record-manual').textContent === 'Record manual {station}'")
            assert await js("!document.getElementById('automatic-controls').hidden && !document.getElementById('run-calibration').hidden && !document.getElementById('run-alignment').hidden"), 'Completed setup controls disappeared'
            assert await js("document.getElementById('run-calibration').disabled && document.getElementById('run-alignment').disabled"), 'Completed setup must not bypass workflow order'
            assert await js("document.getElementById('setup-stages-status').textContent.includes('Calibrate: recorded') && document.getElementById('setup-stages-status').textContent.includes('Align: recorded')")
            await click('manual-performed')
            if station == 'Descend':
                state['gripper_unavailable'] = True
                await click('record-manual')
                await until("document.getElementById('manual-record-feedback').textContent.includes('Gripper position could not be read') && !document.getElementById('record-manual').disabled")
                assert teaching.public()['draft']['next_station'] == 'Descend'
                assert await js("!document.getElementById('manual-record-feedback').hidden")
                state['gripper_unavailable'] = False
            await click('record-manual')
            await until("!document.getElementById('manual-performed').checked")
        assert await js("document.getElementById('review-steps').children.length === 5")
        await screenshot('plate_workflow_desktop')
        robot.x = 280.
        await click('waypoint')
        await until("document.getElementById('review-steps').children.length === 6 && !document.getElementById('capture').disabled")
        robot.x = 310.
        await click('capture')
        await until("document.getElementById('review-steps').children.length === 7 && !document.getElementById('undo').disabled")
        await click('undo')
        await until("document.getElementById('review-steps').children.length === 6 && !document.getElementById('capture').disabled")
        await click('capture')
        await until("document.getElementById('review-steps').children.length === 7 && !document.getElementById('reviewed').disabled")
        assert await js("document.getElementById('save').disabled")
        await screenshot('teach_review_desktop')
        assert not draggo.blocks_motion and fake_rpc.state['disabled'] and not fake_rpc.state['drag']
        await click('reviewed')
        await click('save')
        await until("!document.getElementById('run').hidden && document.getElementById('routine-select').value !== ''")
        assert await js("document.getElementById('start-run').disabled && document.getElementById('pause').disabled && document.getElementById('stop').disabled")
        assert await js("document.getElementById('progress').value === 0")
        exported = await js("fetch(document.getElementById('export').href).then(r => r.json())")
        assert exported['waypoints'][0]['pose_mm']['X'] == 250
        assert exported['waypoints'][6]['pose_mm']['X'] == 310
        assert not exported['execution']['ready']
        assert exported['workflow'] == ['Home','Calibrate','Align','Descend','Grip','Hamilton']
        assert exported['waypoints'][3]['command'] is None
        assert exported['waypoints'][4]['gripper']['E1'] == .2
        before_check_calls = list(robot.gripper_calls), list(fake_rpc.calls), list(robot.program_calls)
        await click('check-routine')
        await until("document.getElementById('routine-check-issues').children.length > 0 && !document.getElementById('check-routine').disabled")
        assert await js("document.getElementById('routine-check-status').textContent.includes('Correct the listed')")
        assert before_check_calls == (robot.gripper_calls, fake_rpc.calls, robot.program_calls)
        await click('plan-pickup')
        await until("document.getElementById('pickup-plan-status').textContent.includes('reviewing pickup logs')")
        assert len(fake_pickup_planner.calls)==1
        assert before_check_calls == (robot.gripper_calls, fake_rpc.calls, robot.program_calls)
        assert await js("document.getElementById('plan-pickup').disabled")
        fake_pickup_planner.active=False
        await screenshot('run_saved_desktop')
        await click('open-plate-setup')
        assert await js("!document.getElementById('teach').hidden && !document.getElementById('automatic-controls').hidden")
        await js("document.querySelector('[data-stage=run]').click()")
        assert await js("document.getElementById('imitate-descend').disabled")
        fake_descent.ready = True
        await click('refresh')
        assert await js("document.getElementById('imitate-descend').disabled")
        await click('descend-ready')
        await until("!document.getElementById('imitate-descend').disabled")
        assert await js("document.getElementById('imitate-descend').textContent === 'Descend' && !document.getElementById('imitate-grip')")
        await click('imitate-descend')
        await until("!document.getElementById('imitate-stop').disabled")
        assert await js("document.getElementById('imitate-descend').disabled")
        await click('imitate-stop')
        await until("document.getElementById('imitate-stop').disabled")
        assert fake_descent.calls == ['start','stop'], fake_descent.calls
        assert await js("document.getElementById('imitate-descend').parentElement === document.getElementById('run-alignment-again').parentElement")
        await js("document.querySelector('[data-stage=teach]').click()")
        assert await js("document.getElementById('run-descent').parentElement === document.getElementById('run-alignment').parentElement")
        fake_descent.ready=True
        await click('refresh')
        assert await js("document.getElementById('run-descent').disabled")
        await click('teach-descend-ready');await until("!document.getElementById('run-descent').disabled")
        await click('run-descent');await until("!document.getElementById('teach-descent-stop').disabled")
        assert await js("!document.getElementById('teach-descend-ready').checked && document.getElementById('run-descent').disabled")
        await click('teach-descent-stop');await until("document.getElementById('teach-descent-stop').disabled")
        assert fake_descent.calls==['start','stop','start','stop']
        assert await js("document.getElementById('run-grip').parentElement === document.getElementById('run-descent').parentElement")
        fake_grip.ready=True
        await click('refresh');assert await js("document.getElementById('run-grip').disabled")
        await click('teach-grip-ready');await until("!document.getElementById('run-grip').disabled")
        await click('run-grip');await until("!document.getElementById('teach-descent-stop').disabled")
        assert await js("document.getElementById('run-grip').disabled && !document.getElementById('teach-grip-ready').checked")
        await screenshot('position_grip_teach')
        await click('teach-descent-stop');await until("document.getElementById('teach-descent-stop').disabled")
        await js("document.querySelector('[data-stage=run]').click()")
        fake_grip.ready=True
        await click('refresh');await click('grip-ready');await until("!document.getElementById('run-grip-again').disabled")
        await click('run-grip-again');await until("!document.getElementById('imitate-stop').disabled")
        await click('imitate-stop');await until("document.getElementById('imitate-stop').disabled")
        assert fake_grip.calls==['start','stop','start','stop']
        assert await js("!document.getElementById('imitate-grip') && !document.getElementById('manual-grip-panel')")
        assert fake_imitation.calls == []
        await call('Page.reload')
        await until("document.getElementById('saved-status')?.textContent === '1 saved routine'")
        await call('Emulation.setDeviceMetricsOverride', dict(width=390, height=844, deviceScaleFactor=1, mobile=True))
        await js("document.querySelector('[data-stage=run]').click()")
        assert await js("document.documentElement.scrollWidth <= window.innerWidth"), 'Mobile overflow'
        await screenshot('run_mobile')
        await js("document.querySelector('[data-stage=teach]').click()")
        await click('start-teaching')
        await until("!document.getElementById('capture').hidden && !document.getElementById('capture').disabled")
        robot.connected = False
        await click('refresh')
        await until("document.getElementById('robot-status').textContent === 'Robot disconnected'")
        assert await js("document.getElementById('capture').disabled")
        await click('discard')
        await until("!document.getElementById('start-teaching').hidden")
        assert len(teaching.public()['routines']) == 1
        robot.connected=True
        await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1080,deviceScaleFactor=1,mobile=False))
        await call('Page.navigate',dict(url=url.rstrip('/')+'/coactive-test'))
        await until("document.getElementById('coactive-status')?.textContent.includes('Reference ready')")
        assert await js("document.getElementById('coactive-capture').disabled")
        await click('coactive-demonstrated');await click('coactive-capture')
        await until("document.getElementById('coactive-comparison').textContent.includes('end_z_after')")
        assert await js("document.getElementById('coactive-accept').disabled")
        await screenshot('developer_coactive_review')
        await click('coactive-reviewed');await click('coactive-accept')
        await until("document.getElementById('coactive-comparison').textContent.includes('accepted')")
        assert coactive_test['current']['id']=='accepted'
        await until("document.getElementById('latest-route-start').textContent === 'Return to Home-area'")
        await click('latest-route-ready');await click('latest-route-start')
        await until("!document.getElementById('latest-route-stop').disabled")
        await click('latest-route-stop')
        await until("document.getElementById('latest-route-stop').disabled")
        assert fake_latest.calls==['start','stop','start','stop']
        assert not errors, errors
        posts = [path for method, path in requests_seen if method == 'POST']
        assert set(posts) <= {'/researcher/api/routines/'+fake_pickup_planner.calls[0]+'/pickup-plan', '/researcher/api/connect', '/researcher/api/teaching/start',
            '/researcher/api/hand-guiding/start', '/researcher/api/hand-guiding/end',
            '/researcher/api/workflow/Calibrate', '/researcher/api/workflow/Align',
            '/researcher/api/home/start', '/researcher/api/home/stop', '/researcher/api/home/area',
            '/researcher/api/latest-hamilton/start','/researcher/api/latest-hamilton/stop',
            '/developer/api/coactive/capture','/developer/api/coactive/decide',
            '/researcher/api/recorded-return/start', '/researcher/api/recorded-return/stop',
            '/researcher/api/hand-claw/start', '/researcher/api/hand-claw/stop',
            '/researcher/api/descent/start', '/researcher/api/descent/stop',
            '/researcher/api/grip/start','/researcher/api/grip/stop',
            '/researcher/api/teaching/capture', '/researcher/api/teaching/undo',
            '/researcher/api/teaching/save', '/researcher/api/teaching/discard'}, posts
        assert teaching.public()['draft'] is None
        report = dict(ok=True, browser_errors=errors, hardware_requests=0, source='fake controller',
                      checks=['connection', 'confirmed Home return and Stop routing', 'Developer gripper path and explicit Auto preparation', 'claw Stop prevents dispatch', 'explicit DragGo start and verified exit', 'Home-Calibrate-Align-manual Descend-manual Grip-Hamilton', 'draft reload',
                              'undo and recapture', 'review required', 'save and reload', 'measured JSON export',
                              'read-only saved routine IK check displays blockers', 'Haiku pickup proposal routing without robot commands', 'full routine playback unavailable', 'Lua Descent and Stop routing', 'position Grip and Stop routing in Teach and Run; legacy Haiku Grip retired',
                              'disconnect disables capture', 'discard preserves saved routines', 'mobile layout'])
        (OUTPUT / 'browser_check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    OUTPUT.mkdir(parents=True, exist_ok=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.logger.disabled = True  # Expected offline fixture exception.
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='researcher_edge_', ignore_cleanup_errors=True) as profile:
            browser = subprocess.Popen([
                r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                '--headless=new', '--no-first-run', '--no-default-browser-check',
                '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                port_file = Path(profile) / 'DevToolsActivePort'
                for _ in range(100):
                    if port_file.exists():
                        break
                    time.sleep(.1)
                port = int(port_file.read_text().splitlines()[0])
                with urllib.request.urlopen(f'http://localhost:{port}/json', timeout=5) as response:
                    tabs = json.load(response)
                asyncio.run(check(next(t['webSocketDebuggerUrl'] for t in tabs if t['type'] == 'page'),
                                  f'http://127.0.0.1:{server.server_port}'))
            finally:
                browser.terminate()
                browser.wait(timeout=10)
    finally:
        server.shutdown()
        storage.cleanup()
