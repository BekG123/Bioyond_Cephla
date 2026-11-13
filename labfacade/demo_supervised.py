"""Offline three-cycle demonstration with a cycle-2 fault. Never binds hardware."""
import json
from pathlib import Path
import tempfile

from .approval import HumanConsole, Signer
from .events import RunFolder
from .supervised import Operation, SupervisedRun, timeline


def demo(folder=None):
    now=[1800000000.]
    clock=lambda:now[0]
    plate='SU-PRKL-P-2611-0001'
    steps=[]
    names=('deliver_hamilton','protocol','retrieve_hamilton','prepare_loading','deliver_squid','image','retrieve_squid')
    for cycle in range(1,4):
        for name in names:
            steps.append(dict(id=f'{cycle}-{name}',machine='fake_lab',operation=name,
                resources=['lab'],params=dict(cycle=cycle),label=f'Cycle {cycle}: {name}'))
    plan=dict(title='OFFLINE DEMO: three supervised cycles; injected cycle-2 failure',
        plate_id=plate,plates={plate:'bioyond deck'},purpose='DNA reagents (declared, not measured)',
        steps=steps,window=dict(not_before=now[0],expires_at=now[0]+3600),fake=True)
    root=Path(folder or tempfile.mkdtemp(prefix='lacry-supervised-demo-'))
    run=RunFolder.create(root,'fake-experiment',plan,{},clock)
    signer=Signer(b'FAKE-ONLY-demo-key-not-for-live-use')
    human=HumanConsole(run,signer,clock)
    human.approve_plan('fake human in offline test')
    human.attest_presence('fake human in offline test')
    calls=[]
    def execute(step,scheduler):
        calls.append(step['id']);now[0]+=2
        if step['id']=='2-protocol':raise TimeoutError('Injected exact-job completion timeout in cycle 2')
        return dict(ok=True,fake=True,job_id=step['id'])
    operations=[Operation('fake_lab',n,('lab',),'fake fixture',execute) for n in names]
    result=SupervisedRun(run,signer,operations,clock=clock).execute()
    assert calls[-1]=='2-protocol' and len(calls)==9 and result['status']=='unknown'
    return dict(result,record=str(run.path),calls=calls,hardware_commands=0,
                timeline=timeline(steps,{}),note='Fake data and fake human approval; not hardware qualification.')


if __name__=='__main__':print(json.dumps(demo(),indent=2))
