"""Exact port of the SDK's circle detection (FindWellPlateLabel) + CalcCircleZOffset.

FindWellPlateLabel: GaussianBlur(11,11,5) -> HoughCircles(GRADIENT, dp=1.5,
minDist=500, param1=50, param2=150, r 50-300); pair by sep 400-900, ratio 1.2-3.0.
Mark = midpoint of the two centers; big radius = larger circle.

CalcCircleZOffset(Circle2CamDis, ModelR, CurR):
    num = CurR - ModelR;  if |num|<1: num*=0.5
    return -Circle2CamDis * num / (ModelR + num)
Circle2CamDis = CalTabInCam[5] = 0.205 (m) -> *1000 for mm robot moves.
"""
import sys, math
import cv2
import numpy as np


def sdk_detect(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    m = cv2.GaussianBlur(img, (11, 11), 5)
    circles = cv2.HoughCircles(m, cv2.HOUGH_GRADIENT, 1.5, 500,
                               param1=50, param2=150, minRadius=50, maxRadius=300)
    if circles is None:
        return None
    cs = circles[0]
    pair = None
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            a, b = cs[i], cs[j]
            big, small = (a, b) if a[2] >= b[2] else (b, a)
            sep = math.hypot(big[0] - small[0], big[1] - small[1])
            ratio = big[2] / small[2]
            if 400 < sep < 900 and 1.2 < ratio < 3.0:
                pair = (big, small)
                break
        if pair:
            break
    if not pair:
        # fall back to two largest
        cs = sorted(cs, key=lambda c: -c[2])
        big, small = cs[0], cs[1]
    else:
        big, small = pair
    mid = ((big[0] + small[0]) / 2, (big[1] + small[1]) / 2)
    ang = math.degrees(math.atan2(small[1] - big[1], small[0] - big[0]))
    return {"big_r": float(big[2]), "small_r": float(small[2]),
            "big_c": (float(big[0]), float(big[1])),
            "mid": (round(mid[0], 1), round(mid[1], 1)), "angle": round(ang, 2)}


def z_offset_mm(cur_r, model_r=190.4, circle2cam=0.205):
    num = cur_r - model_r
    if abs(num) < 1.0:
        num *= 0.5
    return -circle2cam * num / (model_r + num) * 1000.0


if __name__ == "__main__":
    path = sys.argv[1]
    cam_z = float(sys.argv[2]) if len(sys.argv) > 2 else None
    d = sdk_detect(path)
    print(f"{path.split(chr(92))[-1]}: {d}")
    if d and cam_z is not None:
        dz = -z_offset_mm(d["big_r"])      # tool offset = -CalcCircleZOffset
        trig_z = cam_z + dz
        grasp_z = trig_z - 223.593
        print(f"  SDK big_r={d['big_r']:.1f}  Z-to-trigger={dz:+.2f} mm  "
              f"trigger camZ={trig_z:.2f}  => grasp Z={grasp_z:.2f}")
