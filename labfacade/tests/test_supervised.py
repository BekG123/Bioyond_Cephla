from copy import deepcopy
import pytest
from labfacade import HumanConsole, Signer
from labfacade.events import RunFolder
from labfacade.supervised import Operation, SupervisedRun, timing_samples, timeline


def setup_run(tmp_path, *, approve=True, presence=True, fail=None, count=3):
    now=[1000.]
    clock=lambda:now[0]
    signer=Signer(b'test-supervised-key-0123456789')
    steps=[]
    for i in range(count):
        steps.append(dict(id=str(i),machine='arm',operation='carry',label='Carry plate',params={},
            resources=['arm'],transfer={'plate':'P1','from':'bioyond deck','to':'bioyond deck'}))
    run=RunFolder.create(tmp_path,'test',dict(plates={'P1':'bioyond deck'},steps=steps,
        window={'not_before':900.,'expires_at':5000.}),{},clock)
    human=HumanConsole(run,signer,clock)
    if approve:human.approve_plan('operator')
    if presence:human.attest_presence('operator')
    calls=[]
    def execute(step,scheduler):
        calls.append(step['id']);now[0]+=2
        if fail:fail(step,scheduler,now)
        return {'ok':True}
    scheduler=SupervisedRun(run,signer,[Operation('arm','carry',('arm',),'accepted-skill',execute)],clock=clock)
    return scheduler,run,human,calls,now


def test_one_human_approval_covers_all_steps(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    assert scheduler.execute()['ok']
    assert calls==['0','1','2']
    assert not scheduler.lease.exists()
    assert len([e for e in run.events.read() if e.get('status')=='plan_approved'])==1
    samples=timing_samples([run.path])
    assert samples['arm:carry']==dict(n=3,p50_s=2.,p95_s=2.)
    assert timeline(run.plan['steps'],samples)['p95_total_s']==6.


def test_registry_failure_stops_before_next_transfer_without_erasing_verified_ledger(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    def fail_registry(run):raise OSError('Registry write failed')
    scheduler.custody=fail_registry
    result=scheduler.execute()
    assert result['status']=='paused' and calls==['0']
    assert run.read_json('ledger.json')['plates']['P1']['location']=='bioyond deck'
    assert scheduler.lease.exists()


@pytest.mark.parametrize('approve,presence',[(False,True),(True,False),(False,False)])
def test_no_grants_no_dispatch(tmp_path,approve,presence):
    scheduler,run,human,calls,now=setup_run(tmp_path,approve=approve,presence=presence)
    assert not scheduler.execute()['ok']
    assert calls==[]


def test_fault_stops_and_never_redispatches(tmp_path):
    def fault(step,*_):
        if step['id']=='1':raise TimeoutError('Lost instrument acknowledgement')
    scheduler,run,human,calls,now=setup_run(tmp_path,fail=fault)
    result=scheduler.execute()
    assert result['status']=='unknown'
    assert calls==['0','1']
    assert scheduler.lease.exists()
    assert run.read_json('ledger.json')['plates']['P1']['location']=='unknown'
    human.resume('operator','Inspected, but no resend allowed')
    assert not scheduler.execute()['ok']
    assert calls==['0','1']


def test_lapsed_presence_stops_before_next_step(tmp_path):
    def lapse(step,scheduler,now):now[0]+=301
    scheduler,run,human,calls,now=setup_run(tmp_path,fail=lapse)
    assert scheduler.execute()['status']=='paused'
    assert calls==['0']
    assert scheduler.lease.exists()


def test_changed_plan_fails_signature(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    record=run.read_json('run.json');record['plan']['steps'][0]['params']['speed']=999
    run.write_json('run.json',record)
    assert not scheduler.execute()['ok']
    assert calls==[]


def test_exclusive_lab_lease_never_stolen(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    scheduler.lease.write_text('{"run":"other paused experiment"}')
    assert not scheduler.execute()['ok']
    assert calls==[]
    assert 'other paused' in scheduler.lease.read_text()


def test_expired_window_and_approval(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    now[0]=6000
    assert not scheduler.execute()['ok']
    assert calls==[]


def test_stop_does_not_run_next_unit(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path,fail=lambda step,s,n:s.stop())
    assert scheduler.execute()['status']=='paused'
    assert calls==['0']


def test_no_fake_estimates(tmp_path):
    scheduler,run,*_=setup_run(tmp_path)
    assert timeline(run.plan['steps'],{})['p95_total_s'] is None


def test_unknown_operation_and_custody_refused(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    record=run.read_json('run.json');record['plan']['steps'][0]['transfer']['from']='hamilton'
    run.write_json('run.json',record)
    human.approve_plan('operator')
    with pytest.raises(ValueError,match='custody'):scheduler.validate()
    assert calls==[]


def test_notification_failure_does_not_repeat_motion(tmp_path):
    scheduler,run,human,calls,now=setup_run(tmp_path)
    def broken(event):raise OSError('UI disconnected')
    scheduler.notify=broken
    assert scheduler.execute()['ok']
    assert calls==['0','1','2']


def test_windows_file_sharing_retry_does_not_retry_operations(tmp_path,monkeypatch):
    import os
    from labfacade.atomic_json import write_json
    original=os.replace
    calls=[]
    def busy_twice(source,target):
        calls.append(source)
        if len(calls)<3:raise PermissionError('Windows reader has file open')
        return original(source,target)
    monkeypatch.setattr(os,'replace',busy_twice)
    write_json(tmp_path/'run.json',{'verified':True})
    assert len(calls)==3
    assert (tmp_path/'run.json').read_text().strip().startswith('{')
    assert not list(tmp_path.glob('*.tmp'))
