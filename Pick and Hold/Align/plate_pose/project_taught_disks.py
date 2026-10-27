"""Transfer actual saved disk outlines between annotated plate quadrilaterals.

Pixel-only inspection tool. No hardware imports or production target writes.
Four corresponding plate corners establish scale, rotation and perspective.
Lens distortion and differences between physical feature planes are not solved.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from grid_preview import detect
from vision import DetectionError, finite_array


def quadrilateral(value):
    q = finite_array(value, (4, 2), 'plate corners').astype(np.float32)
    if not cv2.isContourConvex(q) or cv2.contourArea(q) < 25:
        raise DetectionError('Nondegenerate ordered plate corners required.')
    return q


def transform(points, h):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        raise DetectionError('Finite 2D points required.')
    homogeneous = np.column_stack([p, np.ones(len(p))]) @ np.asarray(h).T
    if np.any(abs(homogeneous[:, 2]) < 1e-8) or np.ptp(np.sign(homogeneous[:, 2])):
        raise DetectionError('Projection crosses the projective horizon.')
    return homogeneous[:, :2] / homogeneous[:, 2:]


def measure_disks(image, corners, seeds):
    """Segment the two real printed disks, selected by explicit reference seeds."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = np.zeros(gray.shape, np.uint8)
    cv2.fillConvexPoly(mask, quadrilateral(corners).astype(np.int32), 255)
    threshold, _ = cv2.threshold(gray[mask > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = np.uint8((gray <= threshold) & (mask > 0)) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    selected = {}
    if set(seeds) != {'large', 'small'}:
        raise DetectionError('Large and small reference seeds required.')
    chosen_indices = []
    for label, seed in seeds.items():
        matches = [(i, c) for i, c in enumerate(contours)
                   if cv2.pointPolygonTest(c, tuple(map(float, seed)), False) >= 0]
        if len(matches) != 1:
            raise DetectionError('Reference disk seed does not identify one dark contour: ' + label)
        index, contour = matches[0]
        chosen_indices.append(index)
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        if area < 100 or 4 * np.pi * area / max(perimeter ** 2, 1) < .7:
            raise DetectionError('Reference contour is not a sufficiently round disk: ' + label)
        if any(cv2.pointPolygonTest(quadrilateral(corners), tuple(map(float, p)), True) < 3
               for p in contour[:, 0, :][::max(1, len(contour)//120)]):
            raise DetectionError('Reference disk touches annotated plate boundary.')
        selected[label] = contour[:, 0, :][::max(1, len(contour)//180)].astype(float)
    if len(set(chosen_indices)) != 2:
        raise DetectionError('Both labels identify the same contour.')
    if cv2.contourArea(selected['large'].astype(np.float32)) <= cv2.contourArea(selected['small'].astype(np.float32)):
        raise DetectionError('Disk size labels are reversed.')
    return selected, float(threshold)


def project(source_corners, target_corners, outlines):
    source, target = quadrilateral(source_corners), quadrilateral(target_corners)
    if np.sign(cv2.contourArea(source, oriented=True)) != np.sign(cv2.contourArea(target, oriented=True)):
        raise DetectionError('Corner correspondence mirrors the plate.')
    h = cv2.getPerspectiveTransform(source, target)
    return h, {label: transform(points, h) for label, points in outlines.items()}


def annotated_corners(spec, image):
    """Annotations use a documented display size, not assumed native pixels."""
    size = finite_array(spec['annotation_size_px'], (2,), 'annotation image size')
    if np.any(size <= 0):
        raise DetectionError('Invalid annotation size.')
    return quadrilateral(spec['corners_px']) * np.array([image.shape[1], image.shape[0]]) / size


def run(config, root, output):
    paths = {k: root / config[k]['image'] for k in ('source', 'target')}
    images = {k: cv2.imread(str(p)) for k, p in paths.items()}
    if any(v is None for v in images.values()):
        raise DetectionError('Cannot read both saved plate images.')
    corners = {k: annotated_corners(config[k], images[k]) for k in images}
    spec = config['source']
    scale = np.array([images['source'].shape[1], images['source'].shape[0]]) / spec['annotation_size_px']
    seeds = {k: np.array(v) * scale for k, v in spec['disk_seeds_px'].items()}
    outlines, threshold = measure_disks(images['source'], corners['source'], seeds)
    h, projected = project(corners['source'], corners['target'], outlines)
    unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    norm_h = cv2.getPerspectiveTransform(corners['source'].astype(np.float32), unit)
    fit = None
    grid_error = None
    try:
        fit = detect(images['target'], 6, 8)
    except DetectionError as error:
        # An explicit annotation can produce an inspection overlay even when
        # automatic grid tracking fails. Never report it as detected geometry.
        grid_error = str(error)
    result = dict(status='actual_taught_disk_projection_preview', offline_only=True,
        motion_authorized=False, metric_pose_estimated=False, orientation_resolved=False,
        coordinate_frame='raw_image_pixels', same_outer_dimensions='operator asserted',
        reference_mapping_validated=False, annotation_reviewed=False,
        H_target_from_source=h.tolist(), corners_native_px={k:v.tolist() for k,v in corners.items()},
        mapping_source='manual corner correspondence',
        grid_tracking_valid=fit is not None, grid_tracking_error=grid_error,
        measured_wells=len(fit['points']) if fit else 0, image_fit_rmse_px=fit['rmse'] if fit else None,
        H_target_from_grid=fit['h'].tolist() if fit else None,
        target_rim_grid_coordinates=transform(corners['target'], np.linalg.inv(fit['h'])).tolist() if fit else None,
        source_threshold=threshold,
        images={k:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for k,p in paths.items()},
        annotations=config, virtual_circles=[],
        limitations=['Corners manually annotated from images; physical grasp registration not verified.',
                     'A 180-degree correspondence remains possible; large-left preview is an explicit assumption.',
                     'Raw-image homography does not correct lens distortion or rim/disk/well height differences.',
                     'Projected outlines are not independent depth observations; do not feed radii into the old distance solver.'])
    for label in ('large', 'small'):
        result['virtual_circles'].append(dict(label=label,
            provenance='segmented original printed disk',
            source_outline_px=outlines[label].tolist(),
            normalized_plate_outline=transform(outlines[label], norm_h).tolist(),
            pixels=projected[label].tolist()))
    output.mkdir(parents=True, exist_ok=True)
    for key in ('source', 'target'):
        canvas = images[key].copy()
        size = max(1, round(canvas.shape[1]/1200))
        cv2.polylines(canvas, [np.rint(corners[key]).astype(np.int32)], True, (50,230,50), 2*size)
        if key == 'target' and fit is not None:
            for p in fit['points']:
                cv2.circle(canvas,tuple(np.rint(p).astype(int)),3*size,(50,230,50),-1)
        for label, color in [('large',(0,190,255)),('small',(255,180,30))]:
            points = outlines[label] if key == 'source' else projected[label]
            cv2.polylines(canvas, [np.rint(points).astype(np.int32)], True, color, 3*size)
        text = 'Original printed disks' if key == 'source' else 'Actual disks projected onto 48-well plate - PREVIEW ONLY'
        cv2.rectangle(canvas,(0,0),(canvas.shape[1],48*size),(25,25,25),-1)
        cv2.putText(canvas,text,(15,32*size),cv2.FONT_HERSHEY_SIMPLEX,.65*size,(255,255,255),size,cv2.LINE_AA)
        if not cv2.imwrite(str(output/(key+'_overlay.jpg')), canvas):
            raise OSError('Could not write overlay.')
    # Save the alternative correspondence too, rather than claiming grid orientation.
    _, alternative = project(corners['source'], np.roll(corners['target'],2,axis=0), outlines)
    result['alternative_180_outlines_px']={k:v.tolist() for k,v in alternative.items()}
    (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[3]
    result=run(json.loads(args.annotations.read_text()),root,args.output)
    print(json.dumps({k:result[k] for k in ('status','measured_wells','image_fit_rmse_px','motion_authorized')},indent=2))
