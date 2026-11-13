"""Stage accepted short-side feature while preserving unrelated worktree edits."""
from pathlib import Path
import ast,json,re,subprocess
root=Path.cwd();ui=root/'operator_ui'
def git(*args,input=None):return subprocess.check_output(['git',*args],input=input)
assert not git('diff','--cached','--name-only').strip(), 'Existing staging needs review'
tracked=set(git('ls-files','-z').decode().split('\0'))
seeds=list(ui.glob('*short_side*.py'))+list((ui/'tests').glob('test_*short_side*.py'))
extra=('trajectory_queue.py','holder_rotation_trial.py','build_e2_program.py','build_holder_rotation_program.py','build_holder_speed10_program.py',
       'guarded_home_recovery.py','home_recovery.py','home_attempts.py','ik_home.py','researcher_home.py','robot_service.py','latest_hamilton.py',
       'tests/test_trajectory_queue.py','tests/test_guarded_home_recovery.py','tests/test_holder_rotation_trial.py',
       'tests/test_manual_home_recovery.py','tests/test_home_wrist_correction.py','tests/test_home_preparation_settle.py','tests/test_squid_single_queue.py')
seeds += [ui/name for name in extra]
paths=set();pending=seeds.copy()
while pending:
    p=pending.pop();rel=p.relative_to(root).as_posix()
    if rel in paths:continue
    assert p.exists(),rel
    paths.add(rel);tree=ast.parse(p.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        names=[node.module] if isinstance(node,ast.ImportFrom) else [n.name for n in node.names] if isinstance(node,ast.Import) else []
        for name in names:
            if not name:continue
            for base in (ui,ui/'tests'):
                candidate=base/(name.replace('.','/')+'.py')
                if candidate.exists() and candidate.relative_to(root).as_posix() not in tracked:pending.append(candidate)
paths.update(p.relative_to(root).as_posix() for p in (ui/'reports/holder_short_side').rglob('*.json'))
paths.update(p.relative_to(root).as_posix() for p in (root/'controller').glob('*e2*.bin'))
paths.update(p.relative_to(root).as_posix() for p in (root/'controller').glob('*e2*.manifest.json'))
paths.update(('.gitattributes','Pick and Hold/Grip/short_side_48well_reference.json','Pick and Hold/short_side_hamilton_route.json'))
for folder in ('reports/home_attempt_reviews','reports/home_recovery'):
    directory=ui/folder
    if directory.exists():paths.update(p.relative_to(root).as_posix() for p in directory.rglob('*.json'))
head=git('show','HEAD:operator_ui/app.py').decode('utf-8-sig').replace('\r\n','\n')
work=(ui/'app.py').read_text(encoding='utf-8-sig')
start=work.index("@app.post('/developer/api/hamilton-short-side-trial')")
end=work.index("@app.post('/developer/api/hamilton-stopped-return/preview')",start)
marker="@app.post('/developer/api/hamilton-release/preview')";assert head.count(marker)==1
head=head.replace(marker,work[start:end]+marker)
start=work.index("@app.route('/developer/api/home/manual-recovery'")
end=work.index('@app.post("/seq/center_plate_edges")',start)
marker='@app.post("/seq/center_plate_edges")';assert head.count(marker)==1
head=head.replace(marker,work[start:end]+marker)
marker='ik_home_connection = IKHomeConnection(home_return)\n';assert head.count(marker)==1
head=head.replace(marker,marker+'from guarded_home_recovery import GuardedHomeRecovery\nguarded_home_recovery = GuardedHomeRecovery(ik_home_connection)\n')
compile(head,'staged_app.py','exec')
obs='operator_ui/reports/trajectory_smoothing/Observations.md'
old=git('show','HEAD:'+obs);current=(root/obs).read_bytes();added=[]
for section in re.split(rb'(?m)(?=^#{2,3} )',current):
    title=section.splitlines()[0] if section.splitlines() else b''
    if title in old or not title.startswith(b'#'):continue
    if any(word in section.lower() for word in (b'short-side',b'hover03',b'hover04')):added.append(section)
assert any(b'Accepted short-side pickup' in s for s in added)
hybrids={'operator_ui/app.py':head.encode(),obs:old+b'\n\n'+b'\n'.join(added)}
secret=re.compile(rb'(?:sk-ant-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,})')
for rel in paths:
    data=(root/rel).read_bytes();assert len(data)<90_000_000,rel
    assert not secret.search(data), 'Credential-shaped value in '+rel
    assert not any(part in rel for part in ('credentials','.env','api_key'))
for i in range(0,len(paths),40):
    subprocess.run(['git','-c','core.safecrlf=false','add','--',*sorted(paths)[i:i+40]],check=True,capture_output=True)
for rel,data in hybrids.items():
    oid=git('hash-object','-w','--stdin',input=data).decode().strip()
    git('update-index','--add','--cacheinfo','100644',oid,rel)
changed=[p for p in git('diff','--cached','--name-only','-z').decode().split('\0') if p]
manifest=root/'work/short_side_commit_manifest.json'
manifest.write_text(json.dumps(dict(paths=changed,partial_files=list(hybrids)),indent=2))
print(json.dumps(dict(staged_files=len(changed),manifest=str(manifest),partial_files=list(hybrids))))
