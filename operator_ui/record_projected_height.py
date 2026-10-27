"""Record completed reference-height transfer and offline XY recheck; no hardware."""
import hashlib,json
import cv2
import numpy as np
from projected_disk_trial import ROOT,Perception,DetectionError

FOLDER=ROOT/'operator_ui/reports/projected_height_pilot'
FINAL=FOLDER/'20261026_230306_864789bf.jsonl'
def read(path):return [json.loads(line) for line in path.read_text().splitlines()]

def main():
    rows=read(FINAL);final=rows[-1]['result']
    if not final.get('ok') or not final.get('height_reference_reached') or final.get('motion_requested'):
        raise RuntimeError('Missing stationary final height verification.')
    obs=[e['measurement'] for e in rows if e['event']=='observation']
    corners=np.array([m['tracking']['corners_px'] for m in obs])
    if len(obs)!=6:raise RuntimeError('Expected six final observations.')
    deviation=float(np.linalg.norm(corners[:,None,:,:]-corners[None,:,:,:],axis=3).max())
    p=Perception('anchored_grid',5);p.tracker.template_scale_search=True
    xy=[]
    for event in rows:
        if event['event']!='stationary_image_burst':continue
        try:
            m=p.measure(cv2.imread(event['median_image']),event['pose'])
            xy.append(dict(ok=True,error_xy_mm=m['error_xy_mm'],norm_mm=float(np.linalg.norm(m['error_xy_mm']))))
        except DetectionError as ex:xy.append(dict(ok=False,error=str(ex)))
    attempts=[]
    for path in sorted(FOLDER.glob('20261026_*.jsonl')):
        events=read(path);result=events[-1].get('result',{})
        attempts.append(dict(log=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            ok=result.get('ok'),error=result.get('error'),motion_requested=result.get('motion_requested'),
            final_pose=result.get('final_pose'),scale_response=result.get('scale_response')))
    report=dict(date='2026-10-26',height_reference_transfer_verified=True,
        height_reference_mm=289.129,final_pose=final['final_pose'],speed=5,max_step_mm=2,
        reference=final['reference'],operator_same_bottom_support_confirmed=True,
        final_stationary_observations=6,final_max_corner_difference_px=deviation,
        final_supported_wells=[m['tracking']['supported_wells'] for m in obs],
        final_log=FINAL.relative_to(ROOT).as_posix(),final_log_sha256=hashlib.sha256(FINAL.read_bytes()).hexdigest(),
        attempts=attempts,xy_recheck_at_new_height=xy,
        xy_centered_at_final_height=all(r.get('ok') and r['norm_mm']<=.75 for r in xy) and len(xy)==6,
        absolute_depth_verified=False,alignment_verified=False,grasp_target_created=False,calibration_complete=False,
        tests=dict(grid=10,xy_pilot=14,height_pilot=9),
        notes=[
            'Physical observation-height transfer: successful original calibration Z284.129 plus measured 5 mm taller plate on unchanged bottom support.',
            'The upward step ending at Z280.008 initially failed original-disk composition checks; all saved same-plate scale measurements were reviewed before continuation.',
            'Height-only tracking uses independent well-group fits to the frozen same-plate anchor, with distributed support, stationary corner agreement and size response. It cannot validate the original cross-plate disk mapping or publish XY/grasp targets.',
            'The virtual disks were never used to infer optical depth. Approximate axial distances in step diagnostics are not absolute depth calibration.',
            'Height changes can shift the image center; recheck XY before alignment. No alignment, descent or grip executed.'
        ])
    output=FOLDER/'height_reference_session_20261026.json'
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    reference=dict(schema='cephla.plate-observation-height.v1',plate='operator-confirmed 48-well plate, 20 mm overall height',
        observation_z_mm=289.129,method='Transferred physical height reference',
        same_bottom_support_confirmed=True,source_two_disk_z_mm=284.129,plate_top_difference_mm=5,
        live_arrival_and_relative_scale_verified=True,independent_absolute_depth_verified=False,
        same_support_required=True,valid_for_grasp_height=False,valid_for_alignment_target=False,
        evidence=output.relative_to(ROOT).as_posix(),evidence_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    reference_path=ROOT/'Pick and Hold/Calibration/plate_48_height_reference_20261026.json'
    reference_path.write_text(json.dumps(reference,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(output),reference=str(reference_path),pose=final['final_pose'],
        final_max_corner_difference_px=deviation,wells=report['final_supported_wells'],xy_recheck=xy),indent=2))

if __name__=='__main__':main()
