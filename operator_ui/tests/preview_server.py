"""Isolated browser QA server, port 5003. NO physical hardware APIs/routes.

Uses the fake devices from test_transfer; importing the production app is
deliberately avoided. All non-preview POST requests are rejected.
"""
import json
import time
from flask import Flask, jsonify, request, Response
from test_transfer import UI, PARAMS, CAM, FakeService, FakeVision, Runner
from autonomy import seq_transfer, validate_request, TransferError

app = Flask(__name__, static_folder=str(UI / "static"))
svc, vision, runner = FakeService(), FakeVision(), Runner()

@app.get('/')
def index():
    html=(UI/'static'/'index.html').read_text(encoding='utf-8')
    return html.replace('<body>','<body><div style="background:#6e4214;padding:10px;color:white">OFFLINE UI TEST — fake hardware, real robot controls blocked (port 5003)</div>')

@app.get('/robot_params')
def params():return jsonify(PARAMS)

@app.get('/state')
def state():
    return jsonify(robot=dict(connected=False,pose_mm=svc.pose_mm(),joints=svc.joints(),errors=[]),
                   envelope={**{a:dict(min=v[0],max=v[1]) for a,v in svc.envelope.items()},'enabled':True},
                   camera=dict(connected=False,error='offline test'),sequence=dict(active=runner.active,name=runner.name,state=runner.state),target=runner.target,ts=time.time())

@app.get('/seq')
def seq():return jsonify(runner.snapshot())

@app.get('/transfer/config')
def config():return jsonify(ok=True,markers=vision.W.CAL['marker_offsets'],model_stamps=vision.model_stamps(),marker_size_mm=16.553)

@app.post('/seq/transfer_preview')
def preview():
    try:cfg=validate_request(request.get_json(),preview=True)
    except TransferError as ex:return jsonify(ok=False,error=str(ex)),400
    return jsonify(runner.start('aruco_transfer_preview',seq_transfer,svc,CAM,vision,cfg,PARAMS))

@app.post('/<path:path>')
def block(path):return jsonify(ok=False,error='OFFLINE test server: hardware commands blocked'),403

@app.get('/points')
def points():return jsonify(ok=True,points={},roles={})

@app.get('/frame')
def frame():return jsonify(error='No camera in offline test'),503

@app.get('/zcal')
def zcal():return jsonify(ok=True,z_touch_offset_mm=9,safety_margin_mm=0)

@app.get('/torque_threshold')
def torque():return jsonify(ok=True,band_counts=25)

if __name__=='__main__':app.run(host='127.0.0.1',port=5003,threaded=True)
