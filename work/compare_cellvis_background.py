"""Compare background versus plate registration; diagnostic only."""
from diagnose_cellvis_grid_registration import *
base=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'
first='1a1dbefadbc0413e8ad242d4e287fc75';last='3f0bfe8b02b143309ed28b7883a822fe'
imgs=[GridPatternTracker.gray(cv2.imread(str(base/n/'prepared_median_2.png'))) for n in (first,last)]
report=[]
for name,(x,y,w,h) in {'upper_left':(20,20,300,200),'left_table':(20,220,310,550),'upper_middle':(350,20,650,140)}.items():
    a,b=[GridPatternTracker.signal(img[y:y+h,x:x+w]) for img in imgs]
    shift,response=cv2.phaseCorrelate(a,b,cv2.createHanningWindow((w,h),cv2.CV_32F))
    r=dict(region=name,phase_shift=list(shift),phase_response=response)
    try:
        cc,mat=cv2.findTransformECC(a,b,np.eye(2,3,dtype=np.float32),cv2.MOTION_EUCLIDEAN,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,100,1e-7))
        r.update(correlation=cc,transform=mat.tolist())
    except cv2.error as e:r['error']=str(e)
    report.append(r);print(json.dumps(r),flush=True)
(base/last/'background_comparison.json').write_text(json.dumps(report,indent=2))
