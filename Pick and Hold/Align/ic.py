"""Inverse-compositional Lucas-Kanade similarity alignment, image space only.

Warp maps reference pixels to live pixels. Template gradients, steepest-descent
images and Hessian are cached. Each update is W <- W @ inverse(delta_W).
No robot dependencies, depth estimates, learned model, or hardware commands.
"""
from dataclasses import dataclass
import math
import time

import cv2
import numpy as np


class ICError(ValueError):
    pass


@dataclass(frozen=True)
class ICConfig:
    max_edge: int = 960
    levels: int = 3
    max_iterations: int = 80  # Numerical work per image, not robot convergence.
    update_tolerance_px: float = 0.04
    min_correlation: float = 0.90
    max_normalized_rmse: float = 0.45
    max_rotation_deg: float = 15.0
    min_scale: float = 0.8
    max_scale: float = 1.25


def gray(image):
    if image is None or image.dtype != np.uint8 or image.ndim not in (2, 3):
        raise ICError('Expected an 8-bit camera image')
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def checked_roi(roi, shape):
    if len(roi) != 4 or any(isinstance(v, bool) or int(v) != v for v in roi):
        raise ICError('ROI must be four integers: x, y, width, height')
    x, y, w, h = map(int, roi)
    if min(x, y) < 0 or min(w, h) < 64 or x+w > shape[1] or y+h > shape[0]:
        raise ICError('ROI must be inside the image and at least 64 x 64 pixels')
    return x, y, w, h


def image_quality(image, roi):
    a = gray(image)
    x, y, w, h = checked_roi(roi, a.shape)
    patch = a[y:y+h, x:x+w]
    mean, std = float(patch.mean()), float(patch.std())
    if mean < 8 or mean > 247 or std < 8:
        raise ICError('Plate region is too dark, saturated, or textureless; check lighting and ROI')
    return dict(mean=mean, std=std)


def similarity(dx=0., dy=0., angle_deg=0., scale=1., center=(0., 0.)):
    theta = math.radians(angle_deg)
    r = scale * np.array([[math.cos(theta), -math.sin(theta)],
                         [math.sin(theta), math.cos(theta)]])
    c = np.asarray(center, float)
    m = np.eye(3)
    m[:2, :2] = r
    m[:2, 2] = c + [dx, dy] - r @ c
    return m


class ICAligner:
    def __init__(self, reference, roi, config=None):
        self.config = config or ICConfig()
        self.shape = gray(reference).shape
        self.roi = checked_roi(roi, self.shape)
        self.reference_quality = image_quality(reference, self.roi)
        self.reference = gray(reference)
        self.cache = []
        x, y, w, h = self.roi
        base = min(1., self.config.max_edge / max(self.shape))
        for index in reversed(range(self.config.levels)):
            factor = base / 2**index
            if min(w, h)*factor < 20:
                continue
            size = (round(self.shape[1]*factor), round(self.shape[0]*factor))
            sx, sy = size[0]/self.shape[1], size[1]/self.shape[0]
            resize = np.diag([sx, sy, 1.])
            a = cv2.resize(self.reference, size, interpolation=cv2.INTER_AREA).astype(np.float64)
            a = cv2.GaussianBlur(a, (5, 5), .8)
            x0, y0 = round(x*sx)+2, round(y*sy)+2
            x1, y1 = round((x+w)*sx)-2, round((y+h)*sy)-2
            yy, xx = np.mgrid[y0:y1, x0:x1].astype(float)
            raw = a[y0:y1, x0:x1]
            sigma = raw.std()
            if sigma < 5:
                raise ICError('Reference lost texture at pyramid scale')
            template = (raw-raw.mean())/sigma
            gx = cv2.Sobel(a, cv2.CV_64F, 1, 0, ksize=3)[y0:y1, x0:x1] / (8*sigma)
            gy = cv2.Sobel(a, cv2.CV_64F, 0, 1, ksize=3)[y0:y1, x0:x1] / (8*sigma)
            cx, cy = xx.mean(), yy.mean()
            radius = max(x1-x0, y1-y0)/2
            u, v = (xx-cx)/radius, (yy-cy)/radius
            jac = np.stack([gx, gy, -gx*v+gy*u, gx*u+gy*v], axis=-1).reshape(-1, 4)
            hessian = jac.T @ jac
            condition = float(np.linalg.cond(hessian))
            if not math.isfinite(condition) or condition > 1e7:
                raise ICError('Reference cannot constrain translation, rotation and scale; include both disks')
            self.cache.append(dict(size=size, resize=resize, factor=min(sx,sy),
                coords=np.stack([xx, yy, np.ones_like(xx)], axis=-1).reshape(-1,3),
                patch_shape=template.shape, template=template, solver=np.linalg.solve(hessian, jac.T),
                center=(cx,cy), radius=radius, condition=condition))
        if not self.cache:
            raise ICError('ROI is too small at the configured processing resolution')

    @staticmethod
    def _sample(live, cache, warp):
        coords = cache['coords'] @ warp.T
        height, width = live.shape
        if (coords[:,0].min() < 1 or coords[:,1].min() < 1
                or coords[:,0].max() >= width-2 or coords[:,1].max() >= height-2):
            raise ICError('Tracked plate region leaves the image; reacquire the reference view')
        shape = cache['patch_shape']
        patch = cv2.remap(live.astype(np.float32), coords[:,0].reshape(shape).astype(np.float32),
                         coords[:,1].reshape(shape).astype(np.float32), cv2.INTER_LINEAR)
        if patch.std() < 5 or patch.mean() < 8 or patch.mean() > 247:
            raise ICError('Live plate region has insufficient light or texture')
        return (patch-patch.mean())/patch.std()

    def align(self, image, initial=None, cancel=lambda: False):
        start = time.perf_counter()
        a = gray(image)
        if a.shape != self.shape:
            raise ICError('Camera resolution changed; capture a new reference')
        warp = np.eye(3) if initial is None else np.asarray(initial, float).copy()
        if (warp.shape != (3,3) or not np.isfinite(warp).all()
                or not np.allclose(warp[2], [0,0,1]) or np.linalg.det(warp[:2,:2]) <= 0):
            raise ICError('Invalid initial image warp')
        counts, converged = [], False
        for cache in self.cache:
            live = cv2.resize(a, cache['size'], interpolation=cv2.INTER_AREA).astype(float)
            live = cv2.GaussianBlur(live, (5,5), .8)
            resize = cache['resize']
            local = resize @ warp @ np.linalg.inv(resize)
            converged = False
            for iteration in range(self.config.max_iterations):
                if cancel():
                    raise ICError('IC cancelled')
                warped = self._sample(live, cache, local)
                error = (warped-cache['template']).ravel()
                delta = cache['solver'] @ error
                if not np.isfinite(delta).all() or np.linalg.norm(delta) > 100:
                    raise ICError('IC update diverged; reacquire using both disks')
                angle = math.degrees(delta[2]/cache['radius'])
                scale = math.exp(float(np.clip(delta[3]/cache['radius'], -.3, .3)))
                increment = similarity(delta[0], delta[1], angle, scale, cache['center'])
                local = local @ np.linalg.inv(increment)
                if np.linalg.norm(delta) < self.config.update_tolerance_px:
                    converged = True
                    break
            counts.append(iteration+1)
            warp = np.linalg.inv(resize) @ local @ resize
        warped = self._sample(live, cache, local)
        rmse = float(np.sqrt(np.mean((warped-cache['template'])**2)))
        corr = float(np.mean(warped*cache['template']))
        x,y,w,h = self.roi
        center = np.array([x+w/2,y+h/2,1.])
        shift = (warp @ center-center)[:2]
        scale = float(np.sqrt(np.linalg.det(warp[:2,:2])))
        angle = math.degrees(math.atan2(warp[1,0],warp[0,0]))
        reasons = []
        if not converged:
            reasons.append('image optimization did not converge')
        if corr < self.config.min_correlation or rmse > self.config.max_normalized_rmse:
            reasons.append('reference appearance does not match live image')
        if abs(angle) > self.config.max_rotation_deg or not self.config.min_scale <= scale <= self.config.max_scale:
            reasons.append('image transform is outside the configured local tracking range')
        matched = not reasons
        aligned = matched and np.linalg.norm(shift) < 1. and abs(angle) < .2 and abs(scale-1) < .003
        return dict(ok=matched, matched=matched, image_aligned=bool(aligned),
            reason='; '.join(reasons), warp_reference_to_live=warp.tolist(),
            inverse_warp= np.linalg.inv(warp).tolist(), shift_x_px=float(shift[0]), shift_y_px=float(shift[1]),
            rotation_deg=angle, scale=scale, correlation=corr, normalized_rmse=rmse,
            converged=converged, iterations_per_level=counts, seconds=time.perf_counter()-start,
            motion_commanded=False, robot_alignment_verified=False,
            units='native image pixels; image rotation degrees (positive clockwise); dimensionless scale',
            note='Image match only. Not robot offsets, physical jaw verification, or metric depth.')

    def overlay(self, image, result):
        x,y,w,h = self.roi
        polygon = np.array([[x,y,1],[x+w,y,1],[x+w,y+h,1],[x,y+h,1]],float)
        polygon = (polygon @ np.array(result['warp_reference_to_live']).T)[:,:2]
        out = cv2.cvtColor(image,cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image.copy()
        cv2.polylines(out,[np.round(polygon).astype(np.int32)],True,(0,220,0) if result['ok'] else (0,0,255),5)
        cv2.putText(out, f"IC: dx={result['shift_x_px']:.2f}px dy={result['shift_y_px']:.2f}px yaw={result['rotation_deg']:.3f} scale={result['scale']:.4f}",
                    (25,50),cv2.FONT_HERSHEY_SIMPLEX,1.,(0,220,255),2)
        ratio = min(1.,1400/max(out.shape[:2]))
        return cv2.resize(out,None,fx=ratio,fy=ratio)
