"""LiveDetection equivalent: find the calibration board's two circles.

Usage: py circles.py IMAGE.jpg
Prints JSON: big + small circle (center px, radius px), pair axis angle,
midpoint, and ready flag. Detection: adaptive threshold -> contours ->
circularity + area filtering; the two best circles sorted by radius.
"""
import sys, json, math
import numpy as np
import cv2


def detect(path: str) -> dict:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"ready": False, "error": "cannot read image"}
    h, w = img.shape
    # circles are dark on a bright plate: global Otsu on a blurred copy
    blur = cv2.GaussianBlur(img, (9, 9), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 800 or area > 0.25 * w * h:
            continue
        per = cv2.arcLength(c, True)
        if per == 0:
            continue
        circ = 4 * math.pi * area / (per * per)
        if circ < 0.75:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(c)
        fill = area / (math.pi * r * r)
        if fill < 0.75:
            continue
        # circle interior must be dark, surroundings bright
        mask = np.zeros_like(img)
        cv2.circle(mask, (int(cx), int(cy)), max(3, int(r * 0.7)), 255, -1)
        inner = img[mask > 0].mean()
        ring = np.zeros_like(img)
        cv2.circle(ring, (int(cx), int(cy)), int(r * 1.6), 255, int(r * 0.5))
        outer_vals = img[ring > 0]
        outer = outer_vals.mean() if outer_vals.size else 255
        if outer - inner < 40:
            continue
        cands.append({"cx": round(float(cx), 1), "cy": round(float(cy), 1),
                      "r": round(float(r), 1), "circularity": round(circ, 3),
                      "contrast": round(float(outer - inner), 1)})
    cands.sort(key=lambda c: -c["r"])
    out: dict = {"n_candidates": len(cands), "candidates": cands[:6]}
    # pick big + small: the two largest whose radius ratio is 1.6-3.5
    pair = None
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            big, small = cands[i], cands[j]
            ratio = big["r"] / small["r"]
            if 1.4 <= ratio <= 4.0:
                pair = (big, small)
                break
        if pair:
            break
    if not pair:
        out["ready"] = False
        return out
    big, small = pair
    dx, dy = small["cx"] - big["cx"], small["cy"] - big["cy"]
    out.update({
        "ready": True,
        "big": big, "small": small,
        "separation_px": round(math.hypot(dx, dy), 1),
        "axis_deg_img": round(math.degrees(math.atan2(dy, dx)), 2),
        "midpoint": [round((big["cx"] + small["cx"]) / 2, 1),
                     round((big["cy"] + small["cy"]) / 2, 1)],
    })
    return out


if __name__ == "__main__":
    print(json.dumps(detect(sys.argv[1]), indent=1))
