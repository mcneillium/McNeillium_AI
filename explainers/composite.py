"""Put a screen recording onto the green screen of a stock tablet or phone clip.

    python explainers/composite.py --plate broll/pexels-852316.mp4 --start 0.5 --end 8.5 \
        --screen footage/voice-tablet.mp4 --screen-start 1.9 --out footage/voice-tablet-hands.mp4

Per frame: find the green screen (HSV key), take its convex hull, reduce it to
four corners, smooth them over time, warp the screen recording into that quad,
and keep anything non-green that enters from the screen's edge (fingers) in
front. Tracking markers inside the screen are covered. The result is cropped
around the device and scaled to 1920x1080.
"""
import argparse
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent


def green_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (35, 30, 45), (95, 255, 255))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def quad_from(mask):
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cs, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None, 0
    c = max(cs, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.01, 0.08, 15):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            break
    else:
        ap = cv2.boxPoints(cv2.minAreaRect(hull)).reshape(-1, 1, 2)
    pts = ap.reshape(4, 2).astype(np.float32)
    return pts, cv2.contourArea(hull)


def order_portrait(pts):
    """tl, tr, br, bl with the top being the upper short edge."""
    cx, cy = pts.mean(0)
    pts = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # clockwise on screen
    best = None
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        c, d = pts[(i + 1) % 4], pts[(i + 2) % 4]
        short = np.linalg.norm(a - b) < np.linalg.norm(c - d)
        if short:
            y = (a[1] + b[1]) / 2
            if best is None or y < best[0]:
                best = (y, i)
    i = best[1]
    return np.array([pts[(i + k) % 4] for k in range(4)], np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plate", required=True)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--screen", required=True)
    ap.add_argument("--screen-start", type=float, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--crop", type=float, default=0.6667, help="crop width as a share of the plate")
    ap.add_argument("--dim", type=float, default=0.9, help="screen brightness to sit in the room")
    a = ap.parse_args()

    plate = cv2.VideoCapture(str(ROOT / a.plate))
    fps = plate.get(cv2.CAP_PROP_FPS)
    W, H = int(plate.get(3)), int(plate.get(4))
    screen = cv2.VideoCapture(str(ROOT / a.screen))
    sfps = screen.get(cv2.CAP_PROP_FPS)
    n = int((a.end - a.start) * fps)

    # pass 1: corners per frame
    plate.set(cv2.CAP_PROP_POS_MSEC, a.start * 1000)
    raw, areas = [], []
    for _ in range(n):
        ok, f = plate.read()
        if not ok:
            break
        q, area = quad_from(green_mask(f))
        raw.append(order_portrait(q) if q is not None else None)
        areas.append(area)
    med = float(np.median([x for x in areas if x]))
    quads, prev = [], None
    for q, area in zip(raw, areas):
        if q is None or abs(area - med) / med > 0.12:
            q = prev  # occluded corner: hold the last good quad
        if q is None:
            continue
        prev = q if prev is None else 0.55 * q + 0.45 * prev
        quads.append(prev)
    while len(quads) < len(raw):
        quads.insert(0, quads[0])
    # grow each quad slightly so no green rim survives at the screen edge
    quads = [(q - q.mean(0)) * 1.018 + q.mean(0) for q in quads]
    centre = np.mean([q.mean(0) for q in quads], 0)
    cw = int(W * a.crop) // 2 * 2
    ch = int(cw * 9 / 16) // 2 * 2
    x0 = int(np.clip(centre[0] - cw / 2, 0, W - cw))
    y0 = int(np.clip(centre[1] - ch / 2, 0, H - ch))

    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".part.mp4")
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{cw}x{ch}",
                            "-r", f"{fps}", "-i", "-", "-vf", "scale=1920:1080:flags=lanczos,fps=30,format=yuv420p",
                            "-c:v", "libx264", "-crf", "17", "-preset", "veryfast", str(part)], stdin=subprocess.PIPE)
    plate.set(cv2.CAP_PROP_POS_MSEC, a.start * 1000)
    k3 = np.ones((3, 3), np.uint8)
    for i, q in enumerate(quads):
        ok, f = plate.read()
        if not ok:
            break
        screen.set(cv2.CAP_PROP_POS_MSEC, (a.screen_start + i / fps) * 1000)
        ok, s = screen.read()
        if not ok:
            s = last_s
        last_s = s
        sh, sw = s.shape[:2]
        M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), q)
        warped = cv2.warpPerspective(s, M, (W, H), flags=cv2.INTER_AREA)
        warped = cv2.GaussianBlur(warped, (0, 0), 0.8)
        warped = (warped.astype(np.float32) * a.dim).astype(np.uint8)

        quad = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(quad, q.astype(np.int32), 255)
        g = green_mask(f)
        # fingers: skin-toned pixels inside the screen that reach its edge (markers and glare are not skin)
        ycc = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
        skin = cv2.inRange(ycc, (40, 133, 70), (255, 180, 128))
        skin = cv2.bitwise_and(cv2.bitwise_and(skin, quad), cv2.bitwise_not(g))
        skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, k3)
        skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        border = cv2.subtract(quad, cv2.erode(quad, np.ones((13, 13), np.uint8)))
        num, lab = cv2.connectedComponents(skin)
        touching = np.unique(lab[(border > 0) & (lab > 0)])
        fingers = np.isin(lab, touching) & (lab > 0)
        fingers = cv2.morphologyEx(fingers.astype(np.uint8) * 255, cv2.MORPH_CLOSE, k3)
        replace = cv2.subtract(quad, fingers)
        alpha = cv2.GaussianBlur(replace, (0, 0), 1.2).astype(np.float32)[..., None] / 255.0
        # despill: take the green cast off pixels next to the screen
        near = cv2.dilate(g, np.ones((9, 9), np.uint8)) > 0
        b_, g_, r_ = cv2.split(f)
        g2 = np.where(near, np.minimum(g_, np.maximum(r_, b_)), g_)
        f = cv2.merge([b_, g2, r_])
        comp = (warped.astype(np.float32) * alpha + f.astype(np.float32) * (1 - alpha)).astype(np.uint8)
        enc.stdin.write(comp[y0:y0 + ch, x0:x0 + cw].tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    part.replace(out)
    print(f"composited {out.relative_to(ROOT)}: {len(quads)} frames, crop {cw}x{ch} at {x0},{y0}")


if __name__ == "__main__":
    main()
