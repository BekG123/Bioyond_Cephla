"""Camera-only Falcon plate offset measurement and non-executable transfer preview.

No controller imports or movement commands. Native XYZ registration and gripping
geometry must be commissioned separately; a camera crop is not that registration.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np

class OffsetError(ValueError):
    pass

@dataclass(frozen=True)
class PlateModel:
    labware_id: int
    rows: int
    columns: int
    pitch_mm: float
    length_mm: float
    width_mm: float
    height_mm: float
    top_rim_length_mm: float
    top_rim_width_mm: float

# Hamilton export 166: P48w800kmmtjFAL, Falcon 353078. Identification
# by well count/branding is not confirmation of the exact catalog number.
FALCON48 = PlateModel(166, 6, 8, 13.0, 127.63, 85.47, 20.19, 124.0, 81.80000305)
FALCON96 = PlateModel(226, 8, 12, 9.0, 127.63, 85.11, 14.3, 123.65, 81.54)

def fit_grid(centers, model, pitch_px):
    p = np.asarray(centers, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        raise OffsetError('Invalid circle centers')
    if len(p) < .85 * model.rows * model.columns:
        raise OffsetError('Too few wells for this plate definition')
    delta = p[None, :, :] - p[:, None, :]
    def basis(axis):
        other = 1-axis
        selected = delta[(delta[...,axis] > .7*pitch_px) &
                         (delta[...,axis] < 1.3*pitch_px) &
                         (np.abs(delta[...,other]) < .18*pitch_px)]
        if len(selected) < 10: raise OffsetError('No stable well-grid directions')
        return np.median(selected, axis=0)
    b = np.stack([basis(0), basis(1)])
    coords = p @ np.linalg.inv(b)
    phase = np.angle(np.exp(2j*np.pi*coords).mean(axis=0))/(2*np.pi)
    cells = np.rint(coords-phase).astype(int)
    lattice_error = np.linalg.norm((cells+phase) @ b-p, axis=1)
    good = lattice_error < 4.5
    # Neighbor medians are only an initializer: their small pitch bias compounds
    # across eight columns. Refit the lattice to observed inliers before the
    # unchanged 4.5 px selection and final residual/coverage checks.
    design=np.c_[cells,np.ones(len(cells))]
    for _ in range(2):
        if good.sum()<20 or np.linalg.matrix_rank(design[good])<3:break
        refined=np.linalg.lstsq(design[good],p[good],rcond=None)[0]
        good=np.linalg.norm(design@refined-p,axis=1)<4.5
    p, cells = p[good], cells[good]
    best = None
    for x0 in np.unique(cells[:,0]):
        for y0 in np.unique(cells[:,1]):
            keep = ((cells[:,0]>=x0)&(cells[:,0]<x0+model.columns)&
                    (cells[:,1]>=y0)&(cells[:,1]<y0+model.rows))
            if best is None or keep.sum()>best[0]: best=(keep.sum(),keep,np.array([x0,y0]))
    if best is None or best[0] < .85*model.rows*model.columns:
        raise OffsetError('Well grid does not match the selected plate layout')
    p, cells = p[best[1]], cells[best[1]]-best[2]
    if len(np.unique(cells,axis=0)) != len(cells): raise OffsetError('Ambiguous duplicate wells')
    if len(np.unique(cells[:,0])) != model.columns or len(np.unique(cells[:,1])) != model.rows:
        raise OffsetError('Grid is clipped or outer rows/columns are unobserved')
    local = (cells - [(model.columns-1)/2,(model.rows-1)/2])*model.pitch_mm
    a = np.c_[local,np.ones(len(local))]
    transform = np.linalg.lstsq(a,p,rcond=None)[0]
    errors = np.linalg.norm(a@transform-p,axis=1)
    rms = float(np.sqrt(np.mean(errors**2)))
    if rms > 2.5 or errors.max() > 5:
        raise OffsetError('Well-grid residual is too large')
    spacing = np.linalg.norm(transform[:2],axis=1)*model.pitch_mm
    if np.any(np.abs(spacing/pitch_px-1)>.10):
        raise OffsetError('Well spacing disagrees with selected plate geometry')
    angle = float(np.degrees(np.arctan2(transform[0,1],transform[0,0])))
    return dict(transform=transform, centers=p, local=local, cells=cells,
                rms_pixels=rms, angle_crop_deg=angle)

def detect_grid(gray, model=FALCON48, padding_mm=15, site_length_mm=128.75):
    if gray is None or gray.ndim != 2: raise OffsetError('Expected a grayscale site image')
    scale = gray.shape[1]/(site_length_mm+2*padding_mm)
    pitch = scale*model.pitch_mm
    blurred=cv2.GaussianBlur(gray,(5,5),1)
    candidates=[]
    for threshold in (20,22,24,26):
        circles=cv2.HoughCircles(blurred,cv2.HOUGH_GRADIENT,1,.65*pitch,
            param1=80,param2=threshold,minRadius=round(.33*pitch),maxRadius=round(.52*pitch))
        if circles is None:continue
        try:candidates.append(fit_grid(circles[0,:,:2],model,pitch))
        except OffsetError:continue
    # Each candidate independently satisfies the unchanged well count, geometry
    # and residual checks. Independent exposures are checked by the caller;
    # adjacent Hough thresholds are not independent evidence.
    if not candidates:raise OffsetError('No edge threshold produced a valid well-grid fit')
    centers=np.array([v['transform'][2] for v in candidates])
    if np.max(np.linalg.norm(centers-centers.mean(axis=0),axis=1))/scale>.15:
        raise OffsetError('Well-grid fits disagree on plate center')
    result=min(candidates,key=lambda v:(-len(v['centers']),v['rms_pixels']))
    result['image_shape'] = list(gray.shape)
    result['crop_reference_pixel'] = np.array([(gray.shape[1]-1)/2,(gray.shape[0]-1)/2])
    result['offset_plate_axes_mm'] = (result['transform'][2]-result['crop_reference_pixel']) @ np.linalg.inv(result['transform'][:2])
    return result

def check_rim(gray, grid, model):
    """Independent edge support near all four predicted outer plate sides.

    Grid-derived rectangle is not itself a detected contour. Return measured
    supporting edges and disagreement so an occluded rim cannot pass silently.
    """
    inverse = cv2.invertAffineTransform(grid['transform'].T)
    edges = cv2.Canny(gray,50,130)
    yy,xx = np.nonzero(edges)
    local = np.c_[xx,yy,np.ones(len(xx))] @ inverse.T
    offsets=[]; coverage=[]
    for axis, half, span in ((0,model.top_rim_length_mm/2,model.top_rim_width_mm/2),
                            (1,model.top_rim_width_mm/2,model.top_rim_length_mm/2)):
        for sign in (-1,1):
            # Search the upper rim, not the wider/lower skirt at another Z.
            candidates = np.arange(-1,1.01,.1)
            scores=[]
            for shift in candidates:
                selected = local[(np.abs(local[:,axis]-(sign*half+shift))<.25)&
                                 (np.abs(local[:,1-axis])<span*.75),1-axis]
                bins = np.unique(np.floor((selected+span*.75)/1.5))
                scores.append(len(bins)/max(1,span*1.5/1.5))
            index=int(np.argmax(scores))
            offsets.append(float(candidates[index]));coverage.append(float(min(1,scores[index])))
    center_error = [float(np.mean(offsets[:2])),float(np.mean(offsets[2:]))]
    return dict(side_offsets_mm=offsets, side_edge_coverage=coverage,
                center_disagreement_mm=center_error,
                accepted=bool(min(coverage)>=.55 and np.linalg.norm(center_error)<=1.0))

def register_crop(crop, raw, calibration):
    """Match captured crop to undistorted full image, checking handedness."""
    k=np.array(calibration['CameraCalibration']['CameraMatrix']['Data'],float)
    dist=np.array(calibration['CameraCalibration']['DistortionCoefficients']['Data'],float)
    full=cv2.undistort(raw,k,dist,None,k)
    sift=cv2.SIFT_create(nfeatures=6000)
    kb,db=sift.detectAndCompute(full,None)
    best=None
    for flip in (False,True):
        ka,da=sift.detectAndCompute(cv2.flip(crop,1) if flip else crop,None)
        if da is None or db is None: continue
        pairs=cv2.BFMatcher().knnMatch(da,db,k=2)
        good=[pair[0] for pair in pairs if len(pair)==2 and pair[0].distance<.65*pair[1].distance]
        if len(good)<20: continue
        src=np.float64([ka[m.queryIdx].pt for m in good])
        if flip: src[:,0]=crop.shape[1]-1-src[:,0]
        dst=np.float64([kb[m.trainIdx].pt for m in good])
        homography,mask=cv2.findHomography(src,dst,cv2.RANSAC,2)
        if homography is None: continue
        keep=mask.ravel().astype(bool)
        pred=cv2.perspectiveTransform(src[:,None,:],homography)[:,0,:]
        rms=float(np.sqrt(np.mean(np.sum((pred[keep]-dst[keep])**2,axis=1))))
        if best is None or keep.sum()>best['inliers']:
            best=dict(homography=homography,inliers=int(keep.sum()),rms_pixels=rms,
                      camera_matrix=k,mirrored=flip)
    if best is None or best['inliers']<50 or best['rms_pixels']>.8:
        raise OffsetError('Crop-to-full camera registration is unreliable')
    return best

def camera_offset(grid, registration, calibration, reference_plane_z=14.3, plate_plane_z=20.19):
    """Recover well plane from known pitch; intersect reference ray with it.

    Result remains in exported CAMERA calibration coordinates, not native
    controller coordinates. No metal-deck origin or XY sign is assumed.
    """
    h=registration['homography']; k=registration['camera_matrix']
    image=cv2.perspectiveTransform(grid['centers'][:,None,:].astype(float),h)[:,0,:]
    obj=np.c_[grid['local'],np.zeros(len(image))].astype(float)
    ok,rv,tv=cv2.solvePnP(obj,image,k,np.zeros(5),flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok: raise OffsetError('Plate pose solve failed')
    r=cv2.Rodrigues(rv)[0]; center=tv.ravel();normal=r[:,2]
    predicted=cv2.projectPoints(obj,rv,tv,k,np.zeros(5))[0][:,0,:]
    rms=float(np.sqrt(np.mean(np.sum((predicted-image)**2,axis=1))))
    pixel=cv2.perspectiveTransform(grid['crop_reference_pixel'].reshape(1,1,2),h).reshape(2)
    ray=np.linalg.inv(k)@np.r_[pixel,1]
    rd=np.array(calibration['Rotation']['Data'],float)
    td=np.array(calibration['Translation']['Data'],float).reshape(3)
    origin=-rd.T@td
    deck_ray=rd.T@ray
    # Crop center is defined on the API-requested height plane. Intersecting
    # it with the measured plate plane instead creates a parallax-dependent
    # XY reference and was incorrect when the wrong plate height was used.
    reference_deck=origin+(reference_plane_z-origin[2])/deck_ray[2]*deck_ray
    center_deck=rd.T@(center-td)
    center_pixel=cv2.perspectiveTransform(grid['transform'][2].reshape(1,1,2),h).reshape(2)
    center_ray=rd.T@np.linalg.inv(k)@np.r_[center_pixel,1]
    known_plane_center=origin+(plate_plane_z-origin[2])/center_ray[2]*center_ray
    delta=known_plane_center-reference_deck
    tilt=float(np.degrees(np.arccos(np.clip(abs((rd.T@normal)[2]),0,1))))
    if rms>2.5 or center[2]<=0: raise OffsetError('Plate pose reprojection fails')
    return dict(offset_export_frame_mm=delta.tolist(),
                plate_center_export_frame_mm=center_deck.tolist(),
                known_plane_center_export_frame_mm=known_plane_center.tolist(),
                known_plane_height_mm=plate_plane_z,
                monocular_height_is_diagnostic_only=True,
                reference_center_export_frame_mm=reference_deck.tolist(),
                reference_plane_z_mm=reference_plane_z,
                plane_tilt_deg=tilt, reprojection_rms_pixels=rms,
                coordinate_frame='exported_camera_calibration_NOT_native_controller')

def candidate_translation(source_xyz, destination_xyz, measured_offset_xy):
    """Centered pickup: offset SOURCE only; destination stays at its reference.

    Inputs must already share a validated controller frame. This pure geometry
    helper never grants permission to execute or supplies grip/Z geometry.
    """
    source=np.asarray(source_xyz,float);target=np.asarray(destination_xyz,float)
    offset=np.asarray(measured_offset_xy,float)
    if source.shape!=(3,) or target.shape!=(3,) or offset.shape!=(2,) or not np.isfinite(np.r_[source,target,offset]).all():
        raise OffsetError('Invalid coordinate input')
    source=source.copy();source[:2]+=offset
    return dict(source_xyz=source.tolist(),destination_xyz=target.tolist(),executable=False)

def overlay(gray, grid, rim, model):
    frame=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
    tr=grid['transform']; ref=grid['crop_reference_pixel']; center=tr[2]
    corners=np.array([[-1,-1],[1,-1],[1,1],[-1,1]],float)*[model.top_rim_length_mm/2,model.top_rim_width_mm/2]
    measured=np.c_[corners,np.ones(4)]@tr
    nominal=measured-center+ref
    cv2.polylines(frame,[np.round(nominal).astype('int32')],True,(0,220,255),2)
    cv2.polylines(frame,[np.round(measured).astype('int32')],True,(80,220,80),2)
    for x,y in grid['centers']: cv2.circle(frame,(round(x),round(y)),4,(80,220,80),1)
    cv2.arrowedLine(frame,tuple(np.round(ref).astype(int)),tuple(np.round(center).astype(int)),(255,180,40),3)
    frame=cv2.copyMakeBorder(frame,105,0,0,0,cv2.BORDER_CONSTANT,value=(25,25,25))
    dx,dy=grid['offset_plate_axes_mm']
    lines=['CAMERA PREVIEW ONLY - no robot movement',
           'Yellow: crop-plane reference | Green: fitted upper rim',
           f'Plate axes: {dx:+.2f}, {dy:+.2f} mm | {len(grid["centers"])} / {model.rows*model.columns} wells | rim check: {rim["accepted"]}']
    for i,line in enumerate(lines): cv2.putText(frame,line,(12,26+i*31),cv2.FONT_HERSHEY_SIMPLEX,.55,(240,240,240),1,cv2.LINE_AA)
    return frame

def analyze_folder(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'capture.json').read_text())
    calibration=json.loads((folder/'deck-calibration.json').read_text())
    raw=cv2.imread(str(folder/'raw.png'),0)
    results=[]; offsets=[]
    for name in sorted(manifest['files']):
        if not name.startswith('site4_') or not name.endswith('.png'): continue
        data=(folder/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=manifest['files'][name]['sha256']:
            raise OffsetError('Capture changed: '+name)
        gray=cv2.imread(str(folder/name),0)
        grid=detect_grid(gray)
        rim=check_rim(gray,grid,FALCON48)
        registration=register_crop(gray,raw,calibration)
        estimate=camera_offset(grid,registration,calibration,manifest['crop_plane_above_site_mm'])
        offsets.append(estimate['offset_export_frame_mm'])
        results.append(dict(image=name,observed_wells=len(grid['centers']),
                            grid_rms_pixels=grid['rms_pixels'],angle_crop_deg=grid['angle_crop_deg'],
                            offset_plate_axes_mm=grid['offset_plate_axes_mm'].tolist(),rim=rim,
                            registration={k:v for k,v in registration.items() if k not in ('homography','camera_matrix')},
                            **estimate))
        if not cv2.imwrite(str(folder/(Path(name).stem+'_offset.png')),overlay(gray,grid,rim,FALCON48)):
            raise OSError('Could not save the camera offset preview')
    if len(results)<3: raise OffsetError('Need three stopped-camera samples')
    offsets=np.array(offsets)
    jitter=float(np.linalg.norm(offsets-offsets.mean(axis=0),axis=1).max())
    blockers=['Camera-to-native-controller XY registration is not physically validated.',
              'Falcon 48-well grip and site-3 seating heights require review; the failed run used a 96-well definition.',
              'Vision preview does not authorize hardware movement.']
    if jitter>.5: blockers.append('Stationary offset estimates vary by more than 0.5 mm.')
    if any(not r['rim']['accepted'] for r in results): blockers.append('Rim edge agreement failed.')
    if any(abs(r['angle_crop_deg'])>.5 for r in results): blockers.append('Plate rotation exceeds translation-only preview tolerance.')
    if any(r['plane_tilt_deg']>3 for r in results): blockers.append('Plate plane may be tilted; reseating review required.')
    output=dict(kind='hamilton_plate_offset_preview',serial=manifest['serial'],captured_at=manifest['captured_at'],
                model=FALCON48.__dict__,catalog_identity_confirmed=False,observed_layout='6 x 8',
                operator_estimate_mm=10, operator_estimate_used_to_fit=False,
                mean_offset_export_frame_mm=offsets.mean(axis=0).tolist(),
                repeatability_max_deviation_mm=jitter,frames=results,
                known_plane_centers_export_frame_mm=[r['known_plane_center_export_frame_mm'] for r in results],
                executable=False,motion_sent=False,controller_targets=None,blockers=blockers)
    (folder/'offset_preview.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    return output

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture_folder',type=Path)
    report=analyze_folder(p.parse_args().capture_folder)
    print(json.dumps({k:v for k,v in report.items() if k!='frames'},indent=2))
