"""Stationary reference batches and IC previews. Read-only hardware interfaces.

The only supplied hardware operations are camera capture/info and pose reads.
No reference or image-space result is promoted to the robot's grasp target.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import uuid

import cv2
import numpy as np

from .ic import ICAligner, ICError, checked_roi, image_quality, similarity

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = Path(__file__).resolve().parent / 'references'


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def save_image(path, frame):
    if not cv2.imwrite(str(path), frame):
        raise ICError(f'Could not save {path.name}')


def setup_signature():
    paths = ['grab_skill/calibration.json', 'operator_ui/robot_params.json',
             'Vision_context/S4-VisionDemo/USVisionDemo/VisionServer/Locator/Config/Test/Wide/1/LocatorInfoCV_NEW.json']
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def pose_checked(pose):
    keys = ('X','Y','Z','Rz')
    if not isinstance(pose,dict) or any(k not in pose or not np.isfinite(pose[k]) for k in keys):
        raise ICError('Connected robot pose is required for the reference/preview')
    return {k:float(pose[k]) for k in keys}


def ensure_stationary(a,b):
    if (any(abs(a[k]-b[k]) > .1 for k in ('X','Y','Z'))
            or abs((a['Rz']-b['Rz']+180)%360-180) > .1):
        raise ICError('Arm moved during reference/preview capture; stay stationary and try again')


def circles(path):
    # Existing disk detector, not a second robot connection.
    import teach
    return teach.T.sdk_detect(str(path))


def disk_roi(det, shape):
    if det is None:
        raise ICError('Both disks are not detected. Improve lighting or specify a plate-only ROI')
    boxes = [(np.array(det[k+'_c'])-det[k+'_r'], np.array(det[k+'_c'])+det[k+'_r']) for k in ('big','small')]
    low = np.maximum(0,np.floor(np.min([b[0] for b in boxes],axis=0)-40)).astype(int)
    high = np.minimum([shape[1],shape[0]],np.ceil(np.max([b[1] for b in boxes],axis=0)+40)).astype(int)
    return checked_roi([*low,*(high-low)],shape)


def disk_initial(reference, live):
    if reference is None or live is None:
        return None
    a,b = np.array(reference['mark'][:2]), np.array(live['mark'][:2])
    old = np.linalg.norm(np.array(reference['big_c'])-reference['small_c'])
    new = np.linalg.norm(np.array(live['big_c'])-live['small_c'])
    angle = (live['mark'][2]-reference['mark'][2]+180)%360-180
    return similarity(*(b-a), angle, new/old, center=a)


class ICReferences:
    def __init__(self, root=None):
        self.root = Path(root) if root else DEFAULT_STORE
        self.lock = threading.RLock()
        self.phase = 'idle'
        self.error = ''
        self.result = None
        self.preview_path = None
        self.cached = None

    def active_id(self):
        try: return json.loads((self.root/'active.json').read_text())['id']
        except (FileNotFoundError,KeyError,json.JSONDecodeError): return None

    def folder(self, identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identifier):
            raise ICError('Invalid reference identifier')
        path = (self.root/identifier).resolve()
        if path.parent != self.root.resolve():
            raise ICError('Reference path outside store')
        return path

    def public(self):
        references=[]
        if self.root.exists():
            for path in sorted(self.root.glob('*/manifest.json'),reverse=True):
                try:
                    m=json.loads(path.read_text())
                    if m.get('status')=='ready':
                        references.append({k:m[k] for k in ('id','label','created_utc','count','roi','pose_mm')})
                except (OSError,ValueError,KeyError): continue
        with self.lock:
            return dict(phase=self.phase,error=self.error,result=self.result,
                        active_id=self.active_id(),references=references,motion_enabled=False)

    @staticmethod
    def options(body):
        if body.get('aligned_confirmed') is not True or body.get('plate_only_roi') is not True:
            raise ICError('Confirm manual jaw alignment and a plate-only region before capturing a reference')
        count=body.get('count',10)
        if isinstance(count,bool) or not isinstance(count,int) or not 3<=count<=30:
            raise ICError('Batch size must be an integer from 3 to 30')
        label=str(body.get('label','Aligned plate')).strip()
        if not 1<=len(label)<=80: raise ICError('Reference label must contain 1-80 characters')
        roi=body.get('roi')
        if roi is not None and (not isinstance(roi,list) or len(roi)!=4):
            raise ICError('ROI must be [x,y,width,height], or automatic')
        if roi is not None and (any(isinstance(v,bool) or not isinstance(v,int) for v in roi)
                                or min(roi[:2])<0 or min(roi[2:])<64):
            raise ICError('ROI needs integer coordinates and at least 64 x 64 pixels')
        return dict(count=count,label=label,roi=roi)

    def load(self, identifier=None):
        identifier=identifier or self.active_id()
        if identifier is None: raise ICError('Capture or select an aligned reference first')
        folder=self.folder(identifier)
        try: meta=json.loads((folder/'manifest.json').read_text())
        except (OSError,ValueError) as ex: raise ICError('Reference manifest is unavailable') from ex
        if meta.get('status')!='ready': raise ICError('Reference batch is not complete')
        signature=setup_signature()
        if meta['setup_signature']!=signature:
            raise ICError('Saved camera/robot calibration changed; capture a new aligned reference')
        raw=(folder/'reference.png').read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=meta['reference_sha256']: raise ICError('Reference image hash mismatch')
        with self.lock:
            if self.cached is None or self.cached[:2]!=(identifier,digest):
                image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_GRAYSCALE)
                self.cached=(identifier,digest,ICAligner(image,meta['roi']))
            return meta,self.cached[2]

    def select(self, identifier):
        self.load(identifier)
        write_json(self.root/'active.json',dict(id=identifier))
        with self.lock:
            self.result=None
            self.preview_path=None
        return dict(ok=True,id=identifier)

    def _begin(self, phase):
        with self.lock:
            self.phase,self.error,self.result=phase,'',None
            self.preview_path=None

    def _failed(self,run,ex):
        with self.lock:
            self.phase='stopped' if run.stopped() else 'error'
            self.error=str(ex)
            self.result=dict(ok=False,error=str(ex),motion_commanded=False)
        run.state='stopped' if run.stopped() else 'error'
        run.say(str(ex),'err')
        return self.result

    def capture(self,run,cam,read_pose,options):
        self._begin('capturing')
        folder=None
        meta=None
        try:
            signature=setup_signature()
            pose=pose_checked(read_pose())
            identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
            folder=self.folder(identifier)
            folder.mkdir(parents=True,exist_ok=False)
            meta=dict(schema=1,id=identifier,label=options['label'],created_utc=timestamp(),
                status='capturing',count=options['count'],pose_mm=pose,setup_signature=signature,
                operator_confirmed_jaw_alignment=True,operator_confirmed_plate_only_roi=True,
                pose_synchronized=False,frames=[],motion_commanded=False)
            write_json(folder/'manifest.json',meta)
            frames,quality=[],[]
            first_engine=None
            for index in range(options['count']):
                if run.stopped(): raise ICError('Reference capture cancelled')
                before=pose_checked(read_pose())
                ensure_stationary(pose,before)
                frame=cam.snap()
                after=pose_checked(read_pose())
                ensure_stationary(pose,after)
                path=folder/f'frame_{index:03d}.png'
                save_image(path,frame)
                if index==0:
                    det=circles(path)
                    roi=checked_roi(options['roi'],frame.shape) if options['roi'] else disk_roi(det,frame.shape)
                    first_engine=ICAligner(frame,roi)
                    meta.update(roi=list(roi),disk_detection=det,image_shape=list(frame.shape[:2]),camera=cam.info())
                    if not (meta['camera'].get('device') or {}).get('serial'):
                        raise ICError('Camera serial number is required for a reusable reference')
                q=image_quality(frame,meta['roi'])
                match=first_engine.align(frame,cancel=run.stopped)
                if (not match['ok'] or np.hypot(match['shift_x_px'],match['shift_y_px'])>.75
                        or abs(match['rotation_deg'])>.15 or abs(match['scale']-1)>.002):
                    raise ICError('Plate pattern moved within the stationary reference batch; capture again')
                mono=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY) if frame.ndim==3 else frame
                frames.append(mono)
                quality.append(match)
                meta['frames'].append(dict(image=path.name,captured_utc=timestamp(),pose_before=before,
                    pose_after=after,quality=q,match=match,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                run.say(f'IC reference {index+1}/{options["count"]}: stationary, shift '
                        f'{match["shift_x_px"]:+.2f}/{match["shift_y_px"]:+.2f} px; no motion')
            if run.stopped(): raise ICError('Reference capture cancelled')
            ensure_stationary(pose,pose_checked(read_pose()))
            if setup_signature()!=signature: raise ICError('Calibration changed during capture')
            reference=np.median(np.stack(frames),axis=0).astype(np.uint8)
            engine=ICAligner(reference,meta['roi'])
            reference_path=folder/'reference.png'
            save_image(reference_path,reference)
            save_image(folder/'reference_preview.jpg',engine.overlay(reference,engine.align(reference,cancel=run.stopped)))
            if run.stopped(): raise ICError('Reference capture cancelled')
            meta.update(status='ready',reference_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                        max_batch_shift_px=max(float(np.hypot(r['shift_x_px'],r['shift_y_px'])) for r in quality))
            write_json(folder/'manifest.json',meta)
            write_json(self.root/'active.json',dict(id=identifier))
            with self.lock:
                self.phase='ready'
                self.result=dict(ok=True,id=identifier,count=len(frames),roi=meta['roi'],motion_commanded=False)
            run.say(f'IC reference saved: {identifier}. Review the region; this is not automatic jaw verification.','good')
            return self.result
        except Exception as ex:
            if folder is not None and meta is not None:
                meta.update(status='failed',error=str(ex))
                try: write_json(folder/'manifest.json',meta)
                except OSError: pass  # Preserve the original failure; never activate this batch.
            return self._failed(run,ex)

    def preview(self,run,cam,read_pose,identifier=None):
        self._begin('matching')
        try:
            meta,engine=self.load(identifier)
            if run.stopped(): raise ICError('IC preview cancelled')
            before=pose_checked(read_pose())
            frame=cam.snap()
            after=pose_checked(read_pose())
            ensure_stationary(before,after)
            device=cam.info().get('device') or {}
            ref_device=meta['camera'].get('device') or {}
            if not device.get('serial') or device.get('serial')!=ref_device.get('serial'):
                raise ICError('Camera identity changed or is unavailable')
            folder=self.root/'previews'
            folder.mkdir(parents=True,exist_ok=True)
            stem=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
            raw=folder/(stem+'.png')
            save_image(raw,frame)
            initial=disk_initial(meta['disk_detection'],circles(raw))
            result=engine.align(frame,initial=initial,cancel=run.stopped)
            if run.stopped(): raise ICError('IC preview cancelled')
            ensure_stationary(before,pose_checked(read_pose()))
            result.update(reference_id=meta['id'],captured_utc=timestamp(),pose_before=before,pose_after=after,
                          reference_pose=meta['pose_mm'],initialized_from_disks=initial is not None)
            preview=folder/(stem+'.jpg')
            save_image(preview,engine.overlay(frame,result))
            write_json(folder/(stem+'.json'),result)
            with self.lock:
                self.result=result
                self.preview_path=preview
                self.phase='matched' if result['ok'] else 'rejected'
                self.error=result['reason']
            if not result['ok']: run.state='error'
            run.say(f'IC image shift ({result["shift_x_px"]:+.2f}, {result["shift_y_px"]:+.2f}) px; '
                    f'rotation {result["rotation_deg"]:+.3f} deg; scale {result["scale"]:.4f}; '
                    f'correlation {result["correlation"]:.3f}. No motion.', 'good' if result['ok'] else 'err')
            return result
        except Exception as ex:
            return self._failed(run,ex)
