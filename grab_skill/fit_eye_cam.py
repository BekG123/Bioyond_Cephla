"""Rigorous multi-view fit of the eye-camera mounting + marker world position.

Model per capture i:
    m = T_i + R(alpha_i) @ c + R(alpha_i + bpsi) @ F @ u_i
where
    m       = marker world XY (unknown, 2)
    T_i     = TCP XY (known)
    alpha_i = orientation of the frame the camera is rigidly attached to
              (hypotheses: J2+J3+J4 == Rz ('tool'), J2+J3 ('link'),
               J2 ('inner'), 0 ('world'))
    c       = camera lever arm in that frame (unknown, 2)
    bpsi    = camera yaw offset in that frame (unknown, 1)
    F       = diag(1, f), f = +/-1 (mirror convention of the PnP frame)
    u_i     = marker position in camera frame from PnP (known, 2)

For fixed (hypothesis, f, bpsi) the system is LINEAR in (c, m):
    [R(alpha_i)  I2] [c; m] = T_i ... wait sign: m - R*c = T + R(a+b) F u
Solve least squares; scan bpsi on a fine grid; report best per model.
"""
import numpy as np
import json

D = [  # X, Y, Rz, J2, J3, J4, ux, uy, H, cam_yaw
    (377.7, -173.1, 79.0, -74.726, -99.582, -106.692,  0.50, 12.65, 188.70,  168.989),
    (377.7, -173.1, 94.0, -74.726, -99.582,  -91.692, -7.63, 26.12, 189.36, -176.444),
    (377.7, -173.1, 64.0, -74.726, -99.582, -121.692,  4.65, -2.40, 187.74,  154.031),
    (407.7, -173.1, 79.0, -65.821, -111.499, -103.680, 24.99,  7.87, 186.12,  168.489),
    (377.7, -203.1, 79.0, -74.945, -107.910, -98.144,  4.98, 37.48, 189.08,  168.587),
    (357.7, -153.1, 79.0, -79.485, -87.940, -113.574, -19.12, -0.94, 187.61,  168.905),
]

def R(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])

def alpha(row, hyp):
    X, Y, Rz, J2, J3, J4 = row[:6]
    if hyp == 'tool':   return Rz
    if hyp == 'link':   return J2 + J3
    if hyp == 'inner':  return J2
    if hyp == 'world':  return 0.0

def fit(hyp, f):
    best = None
    for bpsi in np.arange(0.0, 360.0, 0.25):
        A, b = [], []
        for row in D:
            a = alpha(row, hyp)
            u = np.array([row[6], f * row[7]])
            T = np.array([row[0], row[1]])
            rhs = -T - R(a + bpsi) @ u          # m - R(a) c = T + R(a+bpsi) F u
            # unknown vector p = [cx, cy, mx, my]; equation: -R(a) c + m = T + R(a+bpsi)Fu
            M = np.hstack([-R(a), np.eye(2)])
            A.append(M); b.append(T + R(a + bpsi) @ u)
        A = np.vstack(A); b = np.hstack(b)
        p, *_ = np.linalg.lstsq(A, b, rcond=None)
        r = A @ p - b
        rms = float(np.sqrt(np.mean(r ** 2)))
        if best is None or rms < best['rms']:
            best = {'hyp': hyp, 'f': f, 'bpsi': round(float(bpsi), 2),
                    'c': [round(v, 2) for v in p[:2]],
                    'm': [round(v, 2) for v in p[2:]], 'rms': round(rms, 3)}
    return best

results = []
for hyp in ('tool', 'link', 'inner', 'world'):
    for f in (1, -1):
        results.append(fit(hyp, f))
results.sort(key=lambda r: r['rms'])
for r in results:
    print(json.dumps(r))

w = results[0]
print()
print('WINNER:', json.dumps(w))
# marker world yaw consistency for the winner
yaws = []
for row in D:
    a = alpha(row, w['hyp'])
    yw = a + w['bpsi'] + w['f'] * row[9]
    yaws.append((yw + 180.0) % 360.0 - 180.0)
yaws = np.array(yaws)
# unwrap around mean
m0 = yaws[0]
yaws = np.array([((y - m0 + 180) % 360) - 180 + m0 for y in yaws])
print('marker world yaw per capture:', [round(v, 2) for v in yaws],
      'mean', round(float(np.mean(yaws)), 2), 'std', round(float(np.std(yaws)), 3))
print('validation vs anchor (299.46,-317.15): delta =',
      [round(w['m'][0] - 299.46, 1), round(w['m'][1] + 317.15, 1)])
