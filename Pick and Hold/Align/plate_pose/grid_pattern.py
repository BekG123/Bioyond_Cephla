"""Experimental image-only 6x8 grid registration against a frozen reference.

Hough centers provide initialization only. Two disjoint sets of well rings
must independently register to the original image, with local photometric
support across the grid. No metric depth, robot control, or reference updates.
"""
import cv2
import numpy as np
import hashlib
import json
from pathlib import Path
from grid_preview import fit_grid
from project_taught_disks import transform, quadrilateral
from vision import DetectionError
from live_projection import Tracker


class GridPatternTracker:
    size = (1200,800)

    def __init__(self, reference, corners, outlines, *, reference_grid=None):
        self.refinement_motion=cv2.MOTION_HOMOGRAPHY
        self.scale=1200/reference.shape[1]
        self.corners=quadrilateral(corners)*self.scale
        self.outlines={k:np.asarray(v)*self.scale for k,v in outlines.items()}
        self.ref=self.gray(reference)
        self.ref_grid=self.grid(self.ref,reference=True) if reference_grid is None else reference_grid
        self.grid_indices=np.array([[c,r] for r in range(6) for c in range(8)],float)
        self.centers=transform(self.grid_indices,self.ref_grid['h'])
        if (not np.isfinite(self.centers).all() or not 20 < self.ref_grid['pitch'] < 200
                or np.any(self.centers < 0) or np.any(self.centers[:,0] >= 1200)
                or np.any(self.centers[:,1] >= 800)):
            raise DetectionError('Reference well grid is invalid or clipped.')
        self.masks=[np.zeros(self.ref.shape,np.uint8) for _ in range(2)]
        self.local_masks=[]
        radius=round(.43*self.ref_grid['pitch'])
        thickness=round(.15*self.ref_grid['pitch'])
        for g,p in zip(self.grid_indices,self.centers):
            m=np.zeros(self.ref.shape,np.uint8)
            cv2.circle(m,tuple(np.rint(p).astype(int)),radius,255,thickness)
            self.masks[int(sum(g))%2] |= m
            # Retain compact ring pixel indices for local validation.
            self.local_masks.append(np.where(m>0))
        self.reference_signal=self.signal(self.ref)

    @staticmethod
    def gray(image):
        if image is None or image.ndim not in (2,3) or abs(image.shape[1]/image.shape[0]-1.5)>.005:
            raise DetectionError('Grid camera image missing or aspect ratio changed.')
        a=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
        return cv2.resize(a,(1200,800),interpolation=cv2.INTER_AREA)

    @staticmethod
    def signal(a):
        a=a.astype(np.float32)/255
        return cv2.GaussianBlur(a,(5,5),1)-cv2.GaussianBlur(a,(0,0),12)

    @staticmethod
    def grid(gray,reference=False):
        enhanced=cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(gray),(5,5),1.2)
        settings=[(32,46,26),(32,46,18),(28,55,26),(36,48,18),(32,46,22)]
        candidates=[]
        for lo,hi,threshold in settings:
            circles=cv2.HoughCircles(enhanced,cv2.HOUGH_GRADIENT,1.2,75,
                param1=80,param2=threshold,minRadius=lo,maxRadius=hi)
            if circles is None:continue
            try:
                cv2.setRNGSeed(0)
                candidates.append(fit_grid(circles[0,:,:2]))
            except DetectionError:pass
        if candidates:return min(candidates,key=lambda fit:fit['rmse'])
        raise DetectionError('No distributed 40-of-48 grid initialization.')

    def geometry(self,h):
        if not np.isfinite(h).all():raise DetectionError('Nonfinite grid transform.')
        q=quadrilateral(transform(self.corners,h))
        area=cv2.contourArea(q)/cv2.contourArea(self.corners)
        angle=np.degrees(np.arctan2(*(q[1]-q[0])[::-1])-np.arctan2(*(self.corners[1]-self.corners[0])[::-1]))
        if not .65<area<1.5 or abs(angle)>30:
            raise DetectionError('Grid scale/orientation outside local range.')
        if np.any(q<3) or np.any(q[:,0]>1197) or np.any(q[:,1]>797):
            raise DetectionError('Grid-projected plate clipped.')
        return q

    def refine(self,image,seed,mask):
        aligned=cv2.warpPerspective(image,np.linalg.inv(seed),self.size)
        small=np.diag([.5,.5,1.])
        initial=np.eye(3,dtype=np.float32)
        if self.refinement_motion==cv2.MOTION_AFFINE:initial=initial[:2]
        try:
            cc,h=cv2.findTransformECC(cv2.resize(self.reference_signal,(600,400)),
                cv2.resize(self.signal(aligned),(600,400)),initial,
                self.refinement_motion,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,80,1e-6),
                cv2.resize(mask,(600,400),interpolation=cv2.INTER_NEAREST),5)
        except cv2.error as e:raise DetectionError('Whole-grid registration did not converge.') from e
        if not np.isfinite(cc) or cc<.8:raise DetectionError(f'Weak grid-pattern correlation: {cc:.3f}.')
        if h.shape==(2,3):h=np.vstack([h,[0.,0.,1.]])
        return float(cc),seed@np.linalg.inv(small)@h@small

    def track(self,image,seed=None):
        gray=self.gray(image)
        if seed is None:seed=self.grid(gray)['h']@np.linalg.inv(self.ref_grid['h'])
        seed=np.asarray(seed,float)
        self.geometry(seed)
        fits=[self.refine(gray,seed,m) for m in self.masks]
        landmarks=np.vstack([self.corners,*self.outlines.values()])
        transformed=[transform(landmarks,h) for cc,h in fits]
        spread=np.linalg.norm(transformed[0]-transformed[1],axis=1)
        if spread[4:].max()>.8 or spread.max()>2:
            raise DetectionError(f'Independent well groups disagree: disks {spread[4:].max():.3f} px; extent {spread.max():.3f} px.')
        # Use one estimate, never average inconsistent observations.
        cc,h=max(fits,key=lambda x:x[0]);q=self.geometry(h)
        if np.linalg.norm(transform(landmarks,h)-transform(landmarks,seed),axis=1).max()>8:
            raise DetectionError('Grid refinement moved too far from measured wells.')
        aligned=self.signal(cv2.warpPerspective(gray,np.linalg.inv(h),self.size))
        correlations=[]
        for indices in self.local_masks:
            a=self.reference_signal[indices].astype(float);b=aligned[indices].astype(float)
            a-=a.mean();b-=b.mean();norm=np.linalg.norm(a)*np.linalg.norm(b)
            correlations.append(float(a@b/norm) if norm>1e-8 else -1.)
        good=np.array(correlations)>=.65
        g=self.grid_indices[good].astype(int)
        if good.sum()<40 or min(np.bincount(g[:,1],minlength=6))<6 or min(np.bincount(g[:,0],minlength=8))<4:
            raise DetectionError(f'Insufficient distributed well-pattern support: {good.sum()}/48.')
        return dict(status='tracking',tracking_mode='experimental_grid_pattern',motion_authorized=False,
            metric_pose_estimated=False,orientation_resolved=False,reference_updates=0,
            coordinate_frame='preview_image_pixels',image_size_px=list(self.size),
            pattern_correlations=[x[0] for x in fits],well_correlations=correlations,
            group_homographies=[x[1].tolist() for x in fits],
            supported_wells=int(good.sum()),total_wells=48,
            disk_group_spread_px=float(spread[4:].max()),extent_group_spread_px=float(spread.max()),
            H_preview_from_reference_preview=h.tolist(),corners_px=q.tolist(),
            virtual_circles=[dict(label=k,pixels=transform(v,h).tolist()) for k,v in self.outlines.items()])


class AnchoredGridPattern:
    """One frozen same-height reference, measured directly against the original.

All four combinations of original/anchor well-group transforms must agree.
The anchor is never updated from later observations.
"""
    def __init__(self,reference,corners,outlines,anchor):
        self.original=GridPatternTracker(reference,corners,outlines)
        self.registration=self.original.track(anchor)
        scale=anchor.shape[1]/1200
        self.anchor=GridPatternTracker(anchor,np.array(self.registration['corners_px'])*scale,
            {c['label']:np.array(c['pixels'])*scale for c in self.registration['virtual_circles']})
        # Only the local residual at this fixed camera height uses six affine
        # parameters. Perspective remains in the measured grid seed and in the
        # original-to-anchor homography. Independent image gates are unchanged.
        self.anchor.refinement_motion=cv2.MOTION_AFFINE
        self.size=self.original.size
        self.anchor_hash=hashlib.sha256(anchor.tobytes()).hexdigest()
        self.seed_tracker=Tracker(self.anchor.ref,self.anchor.corners,self.anchor.outlines,mode='rim')
        # Initialization only: every frame still registers to the frozen anchor
        # and passes both well-group and original-reference composition gates.
        self.previous_verified_seed=None
        self.template_scale_search=False

    def template_seed(self,image):
        """Whole-plate translation initializer; never a pose acceptance test.

        Uses the frozen plate footprint rather than a repeated individual well.
        Require a distinct correlation peak before local independent refinement.
        """
        signal=self.anchor.signal(self.anchor.gray(image))
        low=np.floor(self.anchor.corners.min(axis=0)).astype(int)
        high=np.ceil(self.anchor.corners.max(axis=0)).astype(int)
        x,y=low;right,bottom=high
        template=self.anchor.reference_signal[y:bottom,x:right]
        candidates=[]
        scales=np.linspace(.85,1.10,26) if self.template_scale_search else [1.]
        for scale in scales:
            resized=cv2.resize(template,None,fx=scale,fy=scale,interpolation=cv2.INTER_LINEAR)
            if resized.shape[0]>signal.shape[0] or resized.shape[1]>signal.shape[1]:continue
            scores=cv2.matchTemplate(signal,resized,cv2.TM_CCOEFF_NORMED)
            _,score,_,location=cv2.minMaxLoc(scores)
            candidates.append((score,location,scale,scores))
        if not candidates:return None,None
        score,location,scale,scores=max(candidates,key=lambda c:c[0])
        other=scores.copy();cx,cy=location
        other[max(0,cy-15):cy+16,max(0,cx-15):cx+16]=-1
        next_score=float(other.max());shift=np.array(location)-scale*low
        center=self.anchor.corners.mean(axis=0)
        displacement=(scale-1)*center+shift
        if (not np.isfinite([score,next_score,*shift]).all() or score<.65
                or score-next_score<.03 or np.linalg.norm(displacement)>150):
            return None,None
        return np.array([[scale,0,shift[0]],[0,scale,shift[1]],[0,0,1.]]),dict(
            method='whole_plate_template',score=float(score),margin=float(score-next_score),
            shift=shift.tolist(),scale=float(scale),accepted_pose=False)

    def texture_seed(self,image):
        """Coarse initialization only; never accepted as a measured pose."""
        tracker=self.seed_tracker
        keys,desc=tracker.sift.detectAndCompute(tracker.feature_gray(image),None)
        if desc is None:return None,None
        matcher=cv2.BFMatcher(cv2.NORM_L2)
        def match(a,b):
            return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(a,b,k=2)
                if len(pair)==2 for m,n in [pair] if m.distance<.7*n.distance}
        forward=match(tracker.desc,desc);reverse=match(desc,tracker.desc)
        pairs=[(i,j) for i,j in forward.items() if reverse.get(j)==i]
        if len(pairs)<25:return None,None
        source=np.float32([tracker.keys[i].pt for i,j in pairs])
        target=np.float32([keys[j].pt for i,j in pairs])
        cv2.setRNGSeed(0)
        h,mask=cv2.findHomography(source,target,cv2.RANSAC,3.,maxIters=3000,confidence=.999)
        if h is None or mask is None or mask.sum()<25:return None,None
        coverage=cv2.contourArea(cv2.convexHull(source[mask.ravel().astype(bool)]))/cv2.contourArea(self.anchor.corners)
        if coverage<.35:return None,None
        return h,dict(method='coarse_rim_texture',inliers=int(mask.sum()),candidates=len(pairs),coverage=coverage,
                      accepted_pose=False)

    def initial_seed(self,image):
        seed,info=self.template_seed(image)
        if seed is None:seed,info=self.texture_seed(image)
        if seed is None:
            try:
                seed=self.anchor.grid(self.anchor.gray(image))['h']@np.linalg.inv(self.anchor.ref_grid['h'])
                info=dict(method='measured_well_grid',accepted_pose=False)
            except DetectionError:
                from grid_rotation_seed import rotation_seed
                seed,info=rotation_seed(self,image)
                if seed is None:raise DetectionError('No distributed grid or verified rotation initializer.')
        return seed,info

    def track(self,image):
        if self.previous_verified_seed is None:
            seed,seed_info=self.initial_seed(image)
        else:
            seed=self.previous_verified_seed.copy()
            seed_info=dict(method='previous_verified_initialization',accepted_pose=False)
        r=self.anchor.track(image,seed=seed)
        landmarks=np.vstack([self.original.corners,*self.original.outlines.values()])
        combinations=[transform(landmarks,np.array(b)@np.array(a))
            for b in r['group_homographies'] for a in self.registration['group_homographies']]
        errors=np.array([np.linalg.norm(a-b,axis=1) for a in combinations for b in combinations])
        disks=float(errors[:,4:].max());extent=float(errors.max())
        if disks>.8 or extent>2:
            raise DetectionError(f'Composed grid groups disagree: disks {disks:.3f} px; extent {extent:.3f} px.')
        h=np.array(r['H_preview_from_reference_preview'])@np.array(self.registration['H_preview_from_reference_preview'])
        q=self.original.geometry(h)
        # Never update from a rejected observation, and never replace an image
        # reference. The existing 8 px refinement bound limits local tracking.
        self.previous_verified_seed=np.array(r['H_preview_from_reference_preview']).copy()
        r.update(tracking_mode='frozen_anchored_grid_pattern',reference_updates=0,
            refinement_model='affine_residual_on_projective_seed',
            initialization=seed_info or dict(method='measured_well_grid',accepted_pose=False),
            anchor_sha256=self.anchor_hash,anchor_registration=self.registration,
            disk_group_spread_px=disks,extent_group_spread_px=extent,
            H_preview_from_reference_preview=h.tolist(),corners_px=q.tolist(),
            virtual_circles=[dict(label=k,pixels=transform(v,h).tolist()) for k,v in self.original.outlines.items()])
        return r


class HeightReferencedGridPattern(AnchoredGridPattern):
    """Frozen height reference with every upstream group fit retained.

    This is a one-time explicit commissioning operation, never an online
    reference update. The source must accept the supplied image. All eight
    original-to-current transform combinations must still pass the original
    0.8/2 pixel composition gates in AnchoredGridPattern.track.
    """
    def __init__(self, source, image):
        registration = source.track(image)
        upstream = source.registration['group_homographies']
        local = registration['group_homographies']
        self.original = source.original
        self.registration = dict(registration)
        self.registration['group_homographies'] = [
            (np.asarray(b) @ np.asarray(a)).tolist()
            for b in local for a in upstream]
        scale = image.shape[1] / 1200
        height_from_source = (np.asarray(registration['H_preview_from_reference_preview'])
                              @ np.linalg.inv(source.registration['H_preview_from_reference_preview']))
        grid_h = height_from_source @ source.anchor.ref_grid['h']
        centers = transform(source.anchor.grid_indices, grid_h).reshape(6, 8, 2)
        pitch = float(np.median(np.linalg.norm(np.diff(centers, axis=1), axis=2)))
        self.anchor = GridPatternTracker(
            image, np.asarray(registration['corners_px']) * scale,
            {c['label']: np.asarray(c['pixels']) * scale
             for c in registration['virtual_circles']},
            reference_grid=dict(h=grid_h, pitch=pitch,
                                source='verified source grid mapped to fixed height image'))
        self.anchor.refinement_motion = cv2.MOTION_AFFINE
        self.size = self.original.size
        self.anchor_hash = hashlib.sha256(image.tobytes()).hexdigest()
        self.seed_tracker = Tracker(self.anchor.ref, self.anchor.corners,
                                    self.anchor.outlines, mode='rim')
        self.previous_verified_seed = None
        self.template_scale_search = True


def commissioned_grid_tracker(root,report,reference):
    folder=Path(root)/'operator_ui/reports/projected_disk_pilot/wider_view_validation_20261026'
    evidence=json.loads((folder/'result.json').read_text())
    entries={Path(row['image']).name:row for row in evidence['results']}
    observations={Path(row['image']).name:row for row in evidence['observations']}
    images=[];origin=None
    for n in range(1,6):
        path=folder/f'fresh_{n}.jpg'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entries[path.name]['sha256']:
            raise DetectionError('Frozen grid anchor image changed.')
        for state in (observations[path.name]['before'],observations[path.name]['after']):
            robot=state['robot'];pose=robot['pose_mm'];origin=origin or pose
            if not robot.get('connected') or not robot.get('ok') or state['sequence']['active']:
                raise DetectionError('Invalid stationary anchor evidence.')
            if any(abs(pose[k]-origin[k])>.1 for k in ('X','Y','Z','Rz')):
                raise DetectionError('Frozen anchor frames are not stationary.')
        images.append(cv2.imread(str(path)))
    anchor=np.median(images,axis=0).astype(np.uint8)
    return AnchoredGridPattern(reference,report['corners_native_px']['target'],
        {c['label']:c['pixels'] for c in report['virtual_circles']},anchor)
