"""Finish the operator-confirmed total 90-degree CCW turn; never retry or start Lua."""
import json
import sys
import time
from proof_lift_plate import api
from holder_rotation_trial import ROOT, quarter_turn_target, verified_return

returning=sys.argv[1:]==['--return-original']
fast=sys.argv[1:]==['--fast']
restore_test=sys.argv[1:]==['--restore-test-start']
assert not sys.argv[1:] or returning or fast or restore_test
label='fast_start_restore' if restore_test else 'return_original' if returning else 'fast_quarter_turn' if fast else 'quarter_turn'
path=ROOT/(label+'_request.json')
if path.exists() or (ROOT/(label+'.json')).exists():
    raise RuntimeError('Quarter turn already attempted; inspect receipt before any retry.')
probe=json.loads((ROOT/'direction_probe.json').read_text())
expected,target=quarter_turn_target(probe,True)
if returning or fast:
    prior=verified_return()[1] if fast else json.loads((ROOT/'quarter_turn.json').read_text())
    assert prior['status'] in (('original_restored','original_restored_by_readback','fast_start_restored') if fast else ('quarter_turn_completed',))
    expected=prior['after']['native']['external_axes']['E2']
    target=probe['origin_degrees']+(90 if fast else 0)
if restore_test:
    expected=json.loads((ROOT/'fast137_startup.json').read_text())['after_native']['external_axes']['E2']
    target=probe['origin_degrees']
s=api('state')
assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect',{'ip':'192.168.201.220'})['ok']
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
record=dict(authorization='User confirmed positive E2 is CCW; requested return to original E2 then faster quarter turn; plate retained by stops/clamp.',
    original_e2=probe['origin_degrees'],expected_start=expected,target=target,started=time.time())
with path.open('x') as f:json.dump(record,f,indent=2)
def save():path.write_text(json.dumps(record,indent=2))
try:
    body=dict(ready=True,empty_gripper=True,holder_clear=True,positive_e2_confirmed_ccw=True)
    if fast:body['plate_retained']=True
    endpoint='restore-test-start' if restore_test else 'return-original' if returning else 'fast-quarter-turn' if fast else 'complete-quarter-turn'
    response=api('developer/api/holder/'+endpoint,body)
    record['response']=response;save()
    if not response.get('ok'):raise RuntimeError(str(response))
    print(json.dumps(dict(started=True,target=target)),flush=True)
    deadline=time.monotonic()+130
    while time.monotonic()<deadline:
        seq=api('seq')
        if not seq['active']:
            record['completion']=seq;save()
            print(json.dumps(seq,indent=2),flush=True)
            if seq['state']!='done' or not seq['result'].get('ok'):raise RuntimeError('Quarter turn did not verify')
            break
        time.sleep(.5)
    else:
        record['stop']=api('program',{'action':'stop'});save()
        raise RuntimeError('Rotation timed out; stop requested. No retry.')
except Exception as error:
    record['error']=str(error);save();raise
