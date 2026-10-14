"""Depth/cloud utilities. Coordinates: camera optical X right, Y down, Z forward; meters."""
import numpy as np
import cv2


def select_cloud(vertices, uv, rgb, minimum=.02, maximum=1., stride=2):
    """Keep only finite measured points and valid mapped texture coordinates.

    SDK vertices already include its calibrated intrinsics/distortion model.
    Never infer scale from a colorized depth image or substitute invalid depth.
    """
    points = np.asarray(vertices, dtype=np.float32).reshape(-1, 3)
    coords = np.asarray(uv, dtype=np.float32).reshape(-1, 2)
    if len(points) != len(coords):
        raise ValueError('Point/texture array size mismatch')
    stride = max(1, int(stride))
    points, coords = points[::stride], coords[::stride]
    mask = np.isfinite(points).all(axis=1) & (points[:, 2] >= minimum) & (points[:, 2] <= maximum)
    points, coords = points[mask].copy(), coords[mask]
    colors = np.full((len(points), 3), 160, dtype=np.uint8)
    good = np.isfinite(coords).all(axis=1) & (coords >= 0).all(axis=1) & (coords <= 1).all(axis=1)
    height, width = rgb.shape[:2]
    pixels = np.floor(coords[good] * [width, height] + .5).astype(np.int32)
    pixels = np.clip(pixels, [0, 0], [width-1, height-1])
    colors[good] = rgb[pixels[:, 1], pixels[:, 0]]
    return points, colors


def depth_preview(depth_m, near=.02, far=1.):
    valid = np.isfinite(depth_m) & (depth_m > 0)
    values = np.clip((np.nan_to_num(depth_m)-near)/(far-near), 0, 1)
    bgr = cv2.applyColorMap((values*255).astype(np.uint8), cv2.COLORMAP_TURBO)
    bgr[~valid] = 0
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def jpeg(rgb):
    ok, data = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError('JPEG encoding failed')
    return data.tobytes()


def ply_bytes(points, colors):
    points = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    colors = np.asarray(colors, dtype=np.uint8).reshape(-1, 3)
    if len(points) != len(colors) or not np.isfinite(points).all():
        raise ValueError('Invalid point cloud')
    data = np.empty(len(points), dtype=[('x','<f4'),('y','<f4'),('z','<f4'),
        ('red','u1'),('green','u1'),('blue','u1')])
    for i, name in enumerate(('x','y','z')): data[name] = points[:, i]
    for i, name in enumerate(('red','green','blue')): data[name] = colors[:, i]
    header = ('ply\nformat binary_little_endian 1.0\ncomment units meters; camera optical frame\n'
        f'element vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\n'
        'property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n')
    return header.encode()+data.tobytes()


def sample_frame():
    """Explicitly synthetic surface for offline display tests, never a camera observation."""
    height, width = 240, 320
    yy, xx = np.mgrid[:height, :width]
    depth = np.full((height, width), .30, dtype=np.float32)
    disk = (xx-160)**2+(yy-120)**2 < 55**2
    depth[disk] = .24
    xyz = np.stack(((xx-160)*depth/280, (yy-120)*depth/280, depth), axis=-1)
    uv = np.stack((xx/(width-1), yy/(height-1)), axis=-1)
    rgb = np.full((height,width,3), [80,110,160], dtype=np.uint8)
    rgb[disk] = [240,170,70]
    return depth, xyz.reshape(-1,3), uv.reshape(-1,2), rgb
