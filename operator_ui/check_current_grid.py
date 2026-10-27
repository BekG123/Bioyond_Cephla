"""Read-only saved-image grid comparison."""
from check_multiview_rim import ROOT,cv2,json,DetectionError
from grid_preview import detect
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
paths=[r['images']['target']['path']]+list((ROOT/'operator_ui/reports/projected_disk_pilot/wider_view_validation_20261026').glob('fresh_*.jpg'))
for path in paths:
    try:
        result=detect(cv2.imread(str(path)))
        print(json.dumps(dict(image=str(path),ok=True,count=len(result['points']),rms=result['rmse'],pitch=result['pitch'],H=result['h'].tolist())))
    except DetectionError as e:print(json.dumps(dict(image=str(path),ok=False,error=str(e))))
