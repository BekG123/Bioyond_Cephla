"""Read-only replay of saved camera observations; never connects to hardware."""
import json
from pathlib import Path
import teach

ROOT=Path(__file__).resolve().parent


def analyze():
    report=[]
    for name in ['20261017_035215_6e7d8a12','20261017_105041_119ddb4c']:
        rows=[json.loads(line) for line in (ROOT/'reports/calibration'/f'{name}.jsonl').read_text().splitlines()]
        obs=[r for r in rows if r['event']=='observation']
        for item in (obs[0],obs[-1]):
            pose=item['pose']
            evaluated=teach.evaluate_ways(item['image'],*[pose[k] for k in ('X','Y','Z','Rz')])
            fresh=next(way['solve'] for way in evaluated['ways'] if way['cfg']=='Wide')
            report.append(dict(trace=name,observation=item['observation'],pose=pose,image=item['image'],
                recorded_mark=item['solve']['mark'],replayed_mark=fresh['mark'],
                recorded_grasp=item['solve']['grasp_estimate'],replayed_grasp=fresh['grasp_estimate']))
    output=ROOT/'reports/researcher_ui/calibration_reference_comparison.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':analyze()
