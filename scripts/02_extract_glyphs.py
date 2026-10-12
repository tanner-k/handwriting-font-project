#!/usr/bin/env python3
"""
Take a photo or scan of the FILLED-IN handwriting template, de-skew/dewarp it
using the four black corner squares as registration marks, crop out each
labeled box using template_layout.json, and save a cleaned-up binary PNG per
character/pair into the glyphs/ directory.

Usage:
    python3 scripts/02_extract_glyphs.py <photo_or_scan.jpg> \
        [--layout template/template_layout.json] [--out glyphs/] [--scale 3]

Writes:
    glyphs/manifest.json         -- label -> {file, is_pair, empty, ink_bbox}
    glyphs/_debug_rectified.png  -- the dewarped page with box outlines drawn
                                     on it, for a quick visual sanity check
    glyphs/<safe_name>.png       -- one cropped, cleaned glyph per box
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

PUNCT_NAMES = {".": "period", ",": "comma", "!": "exclam", "?": "question"}


def safe_name(label: str, is_pair: bool) -> str:
    if is_pair:
        return f"pair_{label}"
    if label in PUNCT_NAMES:
        return f"punct_{PUNCT_NAMES[label]}"
    if label.isdigit():
        return f"digit_{label}"
    if label.isupper():
        return f"upper_{label}"
    return f"lower_{label}"


def order_corners(pts):
    """Order 4 (x,y) points as TL, TR, BL, BR."""
    pts = np.array(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    diff = pts[:, 0] - pts[:, 1]  # x - y
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmax(diff)]
    bl = pts[np.argmin(diff)]
    return tl, tr, bl, br


def find_corner_squares(img_bgr):
    """Detect the 4 solid black registration squares in a photographed page."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # Otsu handles uneven photo lighting far better than a fixed threshold.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    h, w = gray.shape
    img_area = h * w
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < img_area * 0.0002 or area > img_area * 0.03:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        aspect = bw / float(bh)
        if not (0.6 < aspect < 1.6):
            continue
        fill = area / float(bw * bh)
        if fill < 0.6:  # squares are solid; skip sparse/irregular blobs
            continue
        cx, cy = x + bw / 2, y + bh / 2
        # Must sit in the outer margin band near one of the 4 page corners,
        # not somewhere in the middle of the writing grid.
        near_left = cx < w * 0.30
        near_right = cx > w * 0.70
        near_top = cy < h * 0.30
        near_bottom = cy > h * 0.70
        if not ((near_left or near_right) and (near_top or near_bottom)):
            continue
        candidates.append((cx, cy, area))

    if len(candidates) < 4:
        raise RuntimeError(
            f"Only found {len(candidates)} corner-square candidates (need 4). "
            "Retake the photo with even lighting and make sure all 4 black "
            "corner squares are fully visible and not cut off, shadowed, or "
            "overexposed."
        )

    # One best candidate per quadrant, by area (largest solid blob wins).
    quadrants = {"tl": [], "tr": [], "bl": [], "br": []}
    for cx, cy, area in candidates:
        key = ("t" if cy < h / 2 else "b") + ("l" if cx < w / 2 else "r")
        quadrants[key].append((cx, cy, area))

    missing = [q for q, v in quadrants.items() if not v]
    if missing:
        raise RuntimeError(
            f"No corner-square candidate found in quadrant(s) {missing}. "
            "Retake the photo so all 4 corner marks are visible."
        )

    picked = [max(v, key=lambda t: t[2])[:2] for v in quadrants.values()]
    return order_corners(picked)


def rectify(img_bgr, layout, scale):
    W = layout["page_width_pt"] * scale
    H = layout["page_height_pt"] * scale
    tl, tr, bl, br = find_corner_squares(img_bgr)
    src = np.array([tl, tr, bl, br], dtype=np.float32)

    marks = layout["corner_marks_norm"]
    # corner_marks_norm order isn't guaranteed TL/TR/BL/BR -- sort the same way.
    m_tl, m_tr, m_bl, m_br = order_corners([(m["x"], m["y"]) for m in marks])
    dst = np.array(
        [[m_tl[0] * W, m_tl[1] * H], [m_tr[0] * W, m_tr[1] * H],
         [m_bl[0] * W, m_bl[1] * H], [m_br[0] * W, m_br[1] * H]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(src, dst)
    rectified = cv2.warpPerspective(img_bgr, M, (int(round(W)), int(round(H))),
                                     flags=cv2.INTER_CUBIC,
                                     borderValue=(255, 255, 255))
    return rectified


def clean_glyph_crop(gray_crop):
    """Binarize a box crop and strip small noise / stray box-border pixels."""
    _, binary = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    h, w = binary.shape
    cleaned = np.zeros_like(binary)
    min_area = max(4, int(0.0008 * h * w))
    for i in range(1, n_labels):
        x, y, cw, ch, area = stats[i]
        if area < min_area:
            continue  # speck of scan noise
        cleaned[labels == i] = 255
    ink_pixels = int(np.count_nonzero(cleaned))
    ys, xs = np.where(cleaned > 0)
    if len(xs) == 0:
        return cleaned, ink_pixels, None
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return cleaned, ink_pixels, bbox


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="photo or scan of the filled-in template")
    ap.add_argument("--layout", default="template/template_layout.json")
    ap.add_argument("--out", default="glyphs")
    ap.add_argument("--scale", type=float, default=3.0,
                     help="pixels per PDF point in the rectified canvas (higher = more glyph detail)")
    ap.add_argument("--box-margin", type=float, default=0.10,
                     help="fraction to shrink each box inward, to avoid the printed border line")
    args = ap.parse_args()

    with open(args.layout) as f:
        layout = json.load(f)

    img = cv2.imread(args.image)
    if img is None:
        print(f"Could not read image: {args.image}", file=sys.stderr)
        sys.exit(1)

    rectified = rectify(img, layout, args.scale)
    os.makedirs(args.out, exist_ok=True)

    debug = rectified.copy()
    gray_full = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    H, W = gray_full.shape

    manifest = {}
    empty_count = 0
    for box in layout["boxes"]:
        x0, y0, x1, y1 = box["x0"] * W, box["y0"] * H, box["x1"] * W, box["y1"] * H
        bw, bh = x1 - x0, y1 - y0
        mx, my = bw * args.box_margin, bh * args.box_margin
        cx0, cy0, cx1, cy1 = int(x0 + mx), int(y0 + my), int(x1 - mx), int(y1 - my)
        cv2.rectangle(debug, (cx0, cy0), (cx1, cy1), (0, 0, 255), 2)

        crop = gray_full[cy0:cy1, cx0:cx1]
        cleaned, ink_pixels, bbox = clean_glyph_crop(crop)

        name = safe_name(box["label"], box["is_pair"])
        fname = f"{name}.png"
        cv2.imwrite(os.path.join(args.out, fname), cleaned)

        is_empty = ink_pixels < 0.001 * cleaned.size
        if is_empty:
            empty_count += 1
        manifest[box["label"]] = {
            "file": fname,
            "is_pair": box["is_pair"],
            "empty": is_empty,
            "ink_pixels": ink_pixels,
            "ink_bbox": bbox,          # in crop-local pixel coords, or null
            "crop_size": [cleaned.shape[1], cleaned.shape[0]],
        }

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    cv2.imwrite(os.path.join(args.out, "_debug_rectified.png"), debug)

    print(f"Wrote {len(manifest)} glyph crops to {args.out}/")
    if empty_count:
        print(f"WARNING: {empty_count} boxes look empty (no ink detected): "
              f"{[l for l, m in manifest.items() if m['empty']]}", file=sys.stderr)
    print(f"Check {args.out}/_debug_rectified.png to confirm alignment before building the font.")


if __name__ == "__main__":
    main()
