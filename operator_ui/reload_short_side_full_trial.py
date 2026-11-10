"""Load revised trial while the confirmed empty arm is stationary at Home."""
import json
import subprocess
import time
import argparse
from pathlib import Path
import psutil
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_full_trial import reference,FOLDER

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision',choices=('01','02','03','04'),default='01')
parser.add_argument('--attempt',choices=('retry01','retry02','retry03'),default='')
args=parser.parse_args();revision=args.revision
assert not args.attempt or revision=='03'
root=Path(__file__).resolve().parents[1];p,parent,grip=reference(revision);s=api('state')
assert not s['sequence']['active']
if not s['robot'].get('connected'):assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
r=s['robot'];n=DragGoRPC('192.168.201.220').info()
assert r['ok'] and not r['errors'] and r['enabled'] and r['program_state']['state']=='running'
assert not any(n[k] for k in ('moving','error','emergency','drag','manual'))
# Reload is nonmoving; revision 02 restores small holder drift before pickup.
expected_e1=0.0
if args.attempt or revision=='04':
    from short_side_full_trial import receipt
    prep=json.loads(receipt('ready',revision,args.attempt).read_bytes())
    assert prep['status']=='completed' and prep['operator_confirmed_plate_reseated_empty_jaws']
    expected_e1=prep['jaw_position_preserved_mm']
assert abs(n['external_axes']['E1']-expected_e1)<.15 and abs(n['external_axes']['E2']-grip['holder_e2_degrees'])<(.5 if revision in ('02','04') or args.attempt=='retry03' else .1)
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
near(r['pose_mm'],parent['home'],.1)
time.sleep(.3);near(api('state')['robot']['pose_mm'],r['pose_mm'],.05)
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
process=psutil.Process(listeners[0].pid);assert 'operator_ui/app.py' in process.cmdline();env=process.environ()
folder=FOLDER/('reload_full_sequence'+revision+('_'+args.attempt if args.attempt else ''));folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(dict(state=s,native=n),indent=2))
assert api('camera/release',{})['ok'];assert api('disconnect',{})['ok']
process.terminate();process.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False)))
