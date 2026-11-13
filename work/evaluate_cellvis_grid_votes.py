"""Offline candidate extraction sweep; never changes motion or reference."""
import sys,json
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'operator_ui'),str(ROOT/'Pick and Hold/Align/plate_pose')]
from grid_preview import fit_grid
from cellvis24_image_pipeline import decode_reference,median5
from cellvis24_calibration import reference
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_adjustments/59cf68706a604467ab9ff5113f421f0d'
paths=list(folder.glob('prepared_median_*.png'))+list((folder/'trial').glob('prepared_median_*.png'))
for run in ['1a1dbefadbc0413e8ad242d4e287fc75','3f0bfe8b02b143309ed28b7883a822fe','633b3cebf767442ead7dbe91f6366786']:
    paths+=list((ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/run).glob('prepared_median_*.png'))
inputs=[(str(p),cv2.imread(str(p))) for p in paths]
ref=ROOT/'operator_ui/reports/plate_session/cellvis24_validation/observation_53eb4e48abd6'
for i in range(3):inputs.append(('reference_'+str(i),median5([decode_reference((ref/f'burst_{i}_{j}.jpg').read_bytes()) for j in range(5)])))
output=[]
for name,image in inputs:
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);small=cv2.resize(gray,None,fx=1200/3072,fy=1200/3072,interpolation=cv2.INTER_AREA)
    enhanced=cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(small),(5,5),1.2)
    row=dict(image=name,settings={})
    for vote in [18,22,24,26,28,30,34]:
        circles=cv2.HoughCircles(enhanced,cv2.HOUGH_GRADIENT,1.2,80,param1=80,param2=vote,minRadius=37,maxRadius=74)
        try:
            if circles is None:raise ValueError('No candidates')
            fit=fit_grid(circles[0,:,:2],4,6)
            row['settings'][vote]=dict(candidates=len(circles[0]),accepted=len(fit['points']),rmse_native=fit['rmse']*2.56)
        except Exception as error:row['settings'][vote]=dict(error=str(error),candidates=0 if circles is None else len(circles[0]))
    output.append(row)
(folder/'grid_vote_sweep.json').write_text(json.dumps(output,indent=2))
for row in output: print(json.dumps(row))
