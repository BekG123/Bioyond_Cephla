"""Analyze a local saved image only. Does not connect to camera or robot."""
import argparse
import json
from pathlib import Path
import cv2
from vision import analyze, DetectionError


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True,type=Path)
    p.add_argument('--model',required=True,type=Path)
    p.add_argument('--camera',required=True,type=Path)
    p.add_argument('--orientation-template',type=Path)
    p.add_argument('--alignment-context',type=Path,help='Saved transforms and start state; generates IK preview only')
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    try:
        if not args.image.is_file():
            raise DetectionError('Input must be an existing local image file')
        image=cv2.imread(str(args.image))
        if image is None: raise DetectionError('Cannot decode image')
        model=json.loads(args.model.read_text(encoding='utf-8-sig'))
        camera=json.loads(args.camera.read_text(encoding='utf-8-sig'))
        template=cv2.imread(str(args.orientation_template),cv2.IMREAD_GRAYSCALE) if args.orientation_template else None
        result,overlay=analyze(image,model,camera,template)
        cv2.imwrite(str(args.output/'overlay.png'),overlay)
        if args.alignment_context:
            from alignment_preview import preview
            result['alignment_preview']=preview(result,json.loads(args.alignment_context.read_text(encoding='utf-8-sig')))
        result['status']='estimated_offline'
    except (DetectionError,ValueError,KeyError,TypeError,OSError,RuntimeError,cv2.error) as exc:
        result=dict(status='rejected',reason=str(exc),offline_only=True,motion_authorized=False)
    (args.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k in ('status','reason','pose','live_integration_blockers')},indent=2))
    return 0 if result['status']=='estimated_offline' else 2


if __name__=='__main__':
    raise SystemExit(main())
