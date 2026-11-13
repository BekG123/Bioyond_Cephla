"""Stage the accepted holder workflow and dependencies, preserving other work."""
from pathlib import Path
import ast,json,re,subprocess
root=Path.cwd(); ui=root/'operator_ui'
def git(*args,input=None):return subprocess.check_output(['git',*args],input=input)
# Existing entries, if any, are from this helper's interrupted first batch.
tracked=set(git('ls-files','-z').decode().split('\0'))
changed=set(git('diff','--name-only','-z').decode().split('\0'))
names='app calibration_e2 classic_pickup e2_reference execute_continuous_squid_return_20261103 hamilton_release_20261108 hamilton_reteach_trial lacry_agent pickup_home pickup_squid_home_20261103 plate48_workflow projected_pickup regrip_48well_to_3p9 regrip_lift_trial release_empty_home_20261103 researcher researcher_descent robot_service run_short_side_full_sequence01 run_short_side_pickup_to_hamilton squid_48well_retrieval_trial trajectory_queue gripper_closure home_hamilton_exchange hamilton_holder_dropoff home_squid_transfer home_squid_handling home_seating run_record_io run_home_hamilton_squid_handling run_plate_workflow repeat_calibration_hamilton repeat_holder_calibration_20261110 repeat_hamilton_holder_handling station_handling_five_20261110 pickup_squid_for_hamilton_20261109 run_accepted_squid_roundtrip'.split()
pending=[ui/(n+'.py') for n in names if (ui/(n+'.py')).exists()]
pending += [root/p for p in ['README.md','Pick and Hold/Station Handling/Observations.md','Pick and Hold/Calibration/Observations.md','Pick and Hold/Calibration/plate_48_pickup_profile.json','Pick and Hold/Grip/reference_grip.py','Pick and Hold/Align/plate_pose/grid_pattern.py','Pick and Hold/plate_session_workflow.json','operator_ui/e2_reference.json','operator_ui/lacry_prompt.txt','operator_ui/squid_stage_reference.json','operator_ui/reports/corrected_descent_before_reload.json','work/home_squid_live_start.json']]
pending += list((root/'machines').glob('*'))+list((root/'Codex SKILLS').rglob('SKILL.md'))+list((root/'Codex SKILLS').rglob('openai.yaml'))
tests='home_hamilton_exchange hamilton_holder_dropoff home_squid_transfer home_squid_handling handling_cli run_record_io gripper_closure calibration_e2 reference_grip repeat_calibration_hamilton repeat_holder_calibration repeat_hamilton_holder_handling idle_cli pickup_holder plate_session plate48_workflow plate48_calibration_readiness plate48_pending_calibration plate48_image_robustness vision_runtime home_then_calibration lacry_chat_confirmation lacry_pickup projected_pickup hamilton_release hamilton_reteach regrip_lift_trial squid_48well_retrieval_trial'.split()
pending += [ui/'tests'/('test_'+n+'.py') for n in tests]
pending += list((ui/'lua').glob('mod_Trajectory_segment_speeds.lua'))
for folder in ['pickup_holder','plate_session/continuous_grip_handling_144cd4486087457e90ae550b304aa3ee','plate_session/continuous_grip_handling_1b0d4dc9cc984d47bab9138889191f5b','plate_session/continuous_grip_handling_7be41e1ef6f54581b4802c58b1ba678a']:
    pending += list((ui/'reports'/folder).rglob('*.json'))
pending += [ui/'reports/plate_session/hamilton_exchanges/fa1a095a1c414820ad23b1b5220e4b3a.json',ui/'reports/plate_session/continuous_home_seating_95385f08ddd243e8a2e8a304d9de5d6e.json']
seen=set();paths=set();hybrids={};ref_seen=set()
# The developer inspection UI belongs to a different workstream.
app=(ui/'app.py').read_text(encoding='utf-8-sig')
start=app.index("@app.post('/developer/api/dsl/devin/home-check')")
end=app.index('class TorqueRecorder:',start)
app=app[:start]+app[end:]
app=app.replace("app.extensions['developer_diagnostics'] = developer_diagnostics\n",'')
hybrids['operator_ui/app.py']=app.encode()
def add_ref(value):
    if not isinstance(value,str) or len(value)>2000:return
    if not value.endswith(('.json','.yaml','.lua','.py')) or '\n' in value or value in ref_seen:return
    ref_seen.add(value)
    candidates=[Path(value),root/value,ui/value]
    for p in candidates:
        try:
            p=p.resolve(); rel=p.relative_to(root).as_posix()
            if p.is_file() and p.suffix in ('.json','.yaml','.lua','.py') and not any(t in rel for t in ('credentials','api_key','.venv','node_modules')):
                pending.append(p)
        except (OSError,ValueError):pass
def walk(value):
    if isinstance(value,str):add_ref(value)
    elif isinstance(value,dict):
        for v in value.values():walk(v)
    elif isinstance(value,list):
        for v in value:walk(v)
while pending:
    p=pending.pop().resolve()
    if not p.is_file() or p in seen:continue
    seen.add(p);rel=p.relative_to(root).as_posix()
    if rel not in tracked or rel in changed or ('/reports/' in rel and p.suffix=='.json'):paths.add(rel)
    if p.suffix not in ('.py','.json'):continue
    data=hybrids.get(rel,p.read_bytes());s=data.decode('utf-8-sig')
    if p.suffix=='.json':
        try:walk(json.loads(s))
        except ValueError:pass
    else:
        tree=ast.parse(s)
        for n in ast.walk(tree):
            modules=[n.module] if isinstance(n,ast.ImportFrom) else [i.name for i in n.names] if isinstance(n,ast.Import) else []
            for name in modules:
                if not name:continue
                for base in (ui,ui/'tests',root,ui/'squid_bridge'):
                    q=base/(name.replace('.','/')+'.py')
                    if q.exists() and q.name!='devin_review.py':pending.append(q)
            if isinstance(n,ast.Constant) and isinstance(n.value,str):add_ref(n.value)
    # Literal report/config references embedded in descriptions and code.
    for match in re.findall(r'(?:operator_ui/reports/|Pick and Hold/|work/)[^\n\r\"\'`<>]*?\.json',s):add_ref(match)
secret=re.compile(rb'(?:sk-ant-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)')
for rel in paths:
    data=hybrids.get(rel,(root/rel).read_bytes())
    assert len(data)<50_000_000,rel
    assert not secret.search(data),'Credential-shaped value in '+rel
    if rel.endswith('.py'):compile(data,rel,'exec')
ignored=set(subprocess.run(['git','check-ignore','-z','--stdin'],input=('\0'.join(sorted(paths))+'\0').encode(),capture_output=True).stdout.decode().split('\0'))
paths-=ignored
paths.discard('operator_ui/developer_diagnostics.py')
out={'paths':sorted(paths),'partial_files':list(hybrids),'bytes':sum((root/p).stat().st_size for p in paths),'ignored_references':sorted(ignored)}
(root/'work/home_workflow_commit_manifest.json').write_text(json.dumps(out,indent=2))
for i in range(0,len(paths),35):
    subprocess.run(['git','-c','core.safecrlf=false','add','--',*sorted(paths)[i:i+35]],check=True,capture_output=True)
for rel,data in hybrids.items():
    oid=git('hash-object','-w','--stdin',input=data).decode().strip();git('update-index','--add','--cacheinfo','100644',oid,rel)
out={'paths':sorted(paths),'partial_files':list(hybrids),'bytes':sum((root/p).stat().st_size for p in paths)}
(root/'work/home_workflow_commit_manifest.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'staged_files':len(paths),'megabytes':round(out['bytes']/1e6,2),'partial_files':out['partial_files']}))
