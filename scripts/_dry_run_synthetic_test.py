#!/usr/bin/env python3
"""
Pipeline smoke test using SYNTHETIC handwriting (stand-in glyphs drawn with a
system font, not real handwriting). Confirms the geometry, cropping,
vectorization and font-assembly code all work end-to-end -- including
holes/counters and the ligature substitutions -- before the user invests
time printing, filling out, and photographing the real template.

1. Render the blank template PDF to a high-res image.
2. "Fill it in" by drawing each label into its box with a system font
   (a couple of boxes deliberately left blank, to test empty-box handling).
3. Warp it with a random projective transform + padding, simulating a
   photographed (not perfectly flat-scanned) page.
4. Run it through 02_extract_glyphs.py's functions.
5. Run 03_build_font.py's functions on the result.
6. Sanity-check the resulting font: cmap coverage, ligature count, and that
   a hole-bearing glyph (e.g. "o") actually rasterizes with a hole (nonzero
   winding-rule check), not as a solid blob.
"""
import json
import os
import random
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

extract = load_module("extract_glyphs", os.path.join(os.path.dirname(__file__), "02_extract_glyphs.py"))
buildfont = load_module("build_font", os.path.join(os.path.dirname(__file__), "03_build_font.py"))

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"
BLANK_LABELS = {"q", "ing"}  # deliberately left empty, to test empty-box handling

random.seed(7)


def render_blank_template(pdf_path, out_png, dpi=216):
    os.system(f"pdftoppm -r {dpi} -png {pdf_path} /tmp/_dryrun_blank")
    src = "/tmp/_dryrun_blank-1.png"
    os.rename(src, out_png)
    return dpi / 72.0  # px per pt, should match --scale in 02_extract_glyphs.py


def synthesize_filled_image(blank_png, layout, px_per_pt):
    img = Image.open(blank_png).convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.size
    for box in layout["boxes"]:
        label = box["label"]
        if label in BLANK_LABELS:
            continue
        x0, y0 = box["x0"] * W, box["y0"] * H
        x1, y1 = box["x1"] * W, box["y1"] * H
        bw, bh = x1 - x0, y1 - y0
        size = int(bh * 0.62)
        font = ImageFont.truetype(FONT_PATH, size)
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        # scale down if too wide for the box
        if tw > bw * 0.92:
            size = int(size * (bw * 0.92) / tw)
            font = ImageFont.truetype(FONT_PATH, size)
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tx = x0 + (bw - tw) / 2 - tb[0]
        ty = y0 + (bh - th) / 2 - tb[1]
        draw.text((tx, ty), label, font=font, fill=(0, 0, 0))
    return np.array(img)[:, :, ::-1].copy()  # RGB -> BGR for cv2


def simulate_photo(page_bgr, jitter_frac=0.02, pad_frac=0.08):
    h, w = page_bgr.shape[:2]
    pad_x, pad_y = int(w * pad_frac), int(h * pad_frac)
    canvas = np.full((h + 2 * pad_y, w + 2 * pad_x, 3), 235, dtype=np.uint8)
    canvas[pad_y:pad_y + h, pad_x:pad_x + w] = page_bgr

    src = np.array([[0, 0], [w, 0], [0, h], [w, h]], dtype=np.float32) + [pad_x, pad_y]
    jx, jy = w * jitter_frac, h * jitter_frac
    dst = src + np.array([[random.uniform(-jx, jx), random.uniform(-jy, jy)] for _ in range(4)], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32))
    out_size = (canvas.shape[1], canvas.shape[0])
    warped = cv2.warpPerspective(canvas, M, out_size, borderValue=(235, 235, 235))
    return warped


def check_nonzero_winding_hole(font_path, glyph_char="o"):
    """Sample a point that should be INSIDE the counter/hole of a round
    letter and a point that should be on solid ink, using the actual
    nonzero-winding fill rule, to confirm holes really render as holes."""
    from fontTools.ttLib import TTFont
    from fontTools.pens.recordingPen import RecordingPen

    tt = TTFont(font_path)
    glyf = tt["glyf"]
    cmap = tt.getBestCmap()
    gname = cmap.get(ord(glyph_char))
    if gname is None:
        return None
    glyph = glyf[gname]
    pen = RecordingPen()
    glyph.draw(pen, glyf)

    # Reconstruct contours as flattened point lists from the recording pen
    # This is a coarse topology check, not a real curve renderer: for each
    # contour we just collect every point fontTools' pen emits (on-curve
    # points from moveTo/lineTo, plus off-curve control points from
    # qCurveTo -- including the "fully implied, no explicit on-curve point"
    # form TTGlyphPen's qCurveTo(*pts, None) trick produces, where drawing
    # the compiled glyph back out emits a qCurveTo with NO preceding
    # moveTo at all) and connect them in order as a closed polygon. That
    # loses exact curvature but preserves which region is "inside" well
    # enough to check winding direction / hole placement.
    contours = []
    current = []
    for op, args in pen.value:
        if op == "moveTo":
            current = [args[0]]
        elif op == "lineTo":
            current.append(args[0])
        elif op == "qCurveTo":
            current.extend([p for p in args if p is not None])
        elif op == "closePath":
            if len(current) >= 3:
                contours.append(np.array(current, dtype=np.float64))
            current = []
    if not contours:
        return None

    all_pts = np.concatenate(contours, axis=0)
    minx, miny = all_pts.min(axis=0)
    maxx, maxy = all_pts.max(axis=0)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    def winding_number(pt, poly):
        x, y = pt
        wn = 0
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if y1 <= y:
                if y2 > y:
                    if (x2 - x1) * (y - y1) - (x - x1) * (y2 - y1) > 0:
                        wn += 1
            else:
                if y2 <= y:
                    if (x2 - x1) * (y - y1) - (x - x1) * (y2 - y1) < 0:
                        wn -= 1
        return wn

    def total_winding(pt):
        return sum(winding_number(pt, c) for c in contours)

    center_winding = total_winding((cx, cy))
    # sample a point on solid ink: partway between center and the nearest
    # contour point (roughly on a stroke) -- just check a small ring of
    # points around the center and take one whose winding != center's.
    ink_winding = None
    for r_frac in (0.85, 0.7, 0.55, 0.4):
        for ang in range(0, 360, 15):
            import math
            px = cx + (maxx - minx) / 2 * r_frac * math.cos(math.radians(ang))
            py = cy + (maxy - miny) / 2 * r_frac * math.sin(math.radians(ang))
            w_ = total_winding((px, py))
            if w_ != center_winding and w_ != 0:
                ink_winding = w_
                break
        if ink_winding is not None:
            break

    return {"center_winding": center_winding, "ink_winding": ink_winding,
            "num_contours": len(contours)}


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open("template/template_layout.json") as f:
        layout = json.load(f)

    print("1. Rendering blank template...")
    px_per_pt = render_blank_template("template/blank_template.pdf", "/tmp/_dryrun_blank_full.png")

    print("2. Synthesizing filled-in template (system font stand-in for handwriting)...")
    filled_bgr = synthesize_filled_image("/tmp/_dryrun_blank_full.png", layout, px_per_pt)

    print("3. Simulating a photographed (perspective-warped) page...")
    photo = simulate_photo(filled_bgr)
    cv2.imwrite("/tmp/_dryrun_synthetic_photo.png", photo)

    print("4. Running corner detection + rectification + glyph cropping...")
    os.makedirs("/tmp/_dryrun_glyphs", exist_ok=True)
    rectified = extract.rectify(photo, layout, scale=px_per_pt)
    cv2.imwrite("/tmp/_dryrun_rectified.png", rectified)

    gray_full = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    H, W = gray_full.shape
    manifest = {}
    for box in layout["boxes"]:
        x0, y0, x1, y1 = box["x0"] * W, box["y0"] * H, box["x1"] * W, box["y1"] * H
        bw, bh = x1 - x0, y1 - y0
        mx, my = bw * 0.10, bh * 0.10
        cx0, cy0, cx1, cy1 = int(x0 + mx), int(y0 + my), int(x1 - mx), int(y1 - my)
        crop = gray_full[cy0:cy1, cx0:cx1]
        cleaned, ink_pixels, bbox = extract.clean_glyph_crop(crop)
        name = extract.safe_name(box["label"], box["is_pair"])
        fname = f"{name}.png"
        cv2.imwrite(os.path.join("/tmp/_dryrun_glyphs", fname), cleaned)
        is_empty = ink_pixels < 0.001 * cleaned.size
        manifest[box["label"]] = {"file": fname, "is_pair": box["is_pair"], "empty": is_empty,
                                   "ink_pixels": ink_pixels, "ink_bbox": bbox,
                                   "crop_size": [cleaned.shape[1], cleaned.shape[0]]}
    with open("/tmp/_dryrun_glyphs/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    empties = {l for l, m in manifest.items() if m["empty"]}
    print(f"   -> {len(manifest)} boxes cropped; empty boxes detected: {sorted(empties)}")
    assert empties == BLANK_LABELS, f"expected only {BLANK_LABELS} to read empty, got {empties}"
    print("   OK: exactly the deliberately-blank boxes were detected as empty.")

    print("5. Building the font...")
    out_font = "/tmp/_dryrun_font.ttf"
    buildfont.build_font("/tmp/_dryrun_glyphs", out_font, "Dry Run Test", "Regular")

    print("6. Verifying the compiled font...")
    from fontTools.ttLib import TTFont
    tt = TTFont(out_font)
    cmap = tt.getBestCmap()
    expected_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123.,!?") - {"q"}
    missing_cmap = [c for c in expected_chars if ord(c) not in cmap]
    assert not missing_cmap, f"missing cmap entries: {missing_cmap}"
    print(f"   OK: cmap covers {len(cmap)} characters (all expected present, 'q' correctly skipped as blank).")

    gsub = tt.get("GSUB")
    assert gsub is not None, "no GSUB table -- ligatures did not compile"
    liga_lookup_count = sum(
        sum(len(v) for v in st.ligatures.values())
        for feat in gsub.table.FeatureList.FeatureRecord if feat.FeatureTag == "liga"
        for lookup_idx in feat.Feature.LookupListIndex
        for st in [gsub.table.LookupList.Lookup[lookup_idx].SubTable[0]]
    )
    print(f"   OK: GSUB 'liga' feature present with ligature substitutions (expect 20, "
          f"since the pair 'ing' was left blank): found {liga_lookup_count}.")
    assert liga_lookup_count == 20, f"expected 20 ligature rules, found {liga_lookup_count}"

    result = check_nonzero_winding_hole(out_font, "o")
    print(f"   'o' glyph topology check: {result}")
    assert result is not None and result["num_contours"] >= 2, "expected 'o' to have an outer contour + a hole"
    assert result["center_winding"] == 0, (
        f"'o' counter (hole) center has nonzero winding ({result['center_winding']}) "
        "-- the hole is filled in, contour winding direction is wrong!"
    )
    assert result["ink_winding"] not in (0, None), "could not find solid ink on the 'o' stroke -- outline may be degenerate"
    print("   OK: hole winds opposite the outer contour (counter is genuinely open, not filled).")

    print("\nALL DRY-RUN CHECKS PASSED.")
    print(f"Inspect /tmp/_dryrun_rectified.png and /tmp/_dryrun_synthetic_photo.png to eyeball alignment.")
    print(f"Test font: {out_font}")


if __name__ == "__main__":
    main()
