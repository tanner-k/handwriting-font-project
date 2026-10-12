#!/usr/bin/env python3
"""
Turn the cropped glyph PNGs from 02_extract_glyphs.py into a working TrueType
font (.ttf), including OpenType ligature substitution (GSUB 'liga') for the
21 letter-pair boxes ("th" -> a single joined "t_h" glyph, etc.).

No FontForge, no potrace -- both need a system package install that this
sandbox's org policy blocks (apt access to archive.ubuntu.com returns 403).
Everything here is pure Python: OpenCV traces each glyph's ink into contours,
fontTools turns those into quadratic TrueType outlines and assembles the font.

Usage:
    python3 scripts/03_build_font.py \
        --glyphs glyphs/ --out fonts/MyHandwriting.ttf \
        --family "My Handwriting"
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPM = 1000
ASCENT = 800
DESCENT = -200
BASELINE_FRAC = 0.78   # where the baseline sits, as a fraction down from the top of each box crop
SIDE_BEARING = 22      # font units of blank space added on the left and right of each glyph
MIN_CONTOUR_AREA_FRAC = 0.0006  # ignore contours smaller than this fraction of the crop area

AGL_DIGITS = {"0": "zero", "1": "one", "2": "two", "3": "three"}
AGL_PUNCT = {".": "period", ",": "comma", "!": "exclam", "?": "question"}


def glyph_name_for_char(ch: str) -> str:
    if ch in AGL_DIGITS:
        return AGL_DIGITS[ch]
    if ch in AGL_PUNCT:
        return AGL_PUNCT[ch]
    return ch  # letters: 'A'..'Z', 'a'..'z' are already valid glyph names


def ligature_glyph_name(pair: str) -> str:
    return "_".join(glyph_name_for_char(c) for c in pair)


def simplify_contour(contour, crop_area):
    """approxPolyDP with an epsilon chosen adaptively so tiny shapes (the dot
    on an 'i') still get a handful of points instead of collapsing to a line."""
    perim = cv2.arcLength(contour, True)
    if perim <= 0:
        return None
    frac = 0.006
    pts = None
    for _ in range(6):
        eps = max(frac * perim, 0.5)
        approx = cv2.approxPolyDP(contour, eps, True)
        if len(approx) >= 6 or frac <= 0.0005:
            pts = approx
            break
        frac /= 2
    if pts is None:
        pts = cv2.approxPolyDP(contour, max(0.0005 * perim, 0.5), True)
    if len(pts) < 3:
        return None
    return pts.reshape(-1, 2)


def signed_area(points):
    x = points[:, 0]
    y = points[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


def trace_glyph(binary_img, scale, baseline_px, side_bearing):
    """binary_img: uint8, ink=255 on background=0. Returns (TTGlyph, advanceWidth) or None."""
    h, w = binary_img.shape
    crop_area = h * w
    contours, hierarchy = cv2.findContours(binary_img, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    hierarchy = hierarchy[0]  # shape (N, 4): next, prev, firstChild, parent

    def to_font_space(px_pts):
        fx = px_pts[:, 0] * scale + side_bearing
        fy = (baseline_px - px_pts[:, 1]) * scale
        return np.stack([fx, fy], axis=1)

    shapes = []

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < MIN_CONTOUR_AREA_FRAC * crop_area:
            continue
        pts = simplify_contour(contour, crop_area)
        if pts is None or len(pts) < 3:
            continue

        font_pts = to_font_space(pts.astype(np.float64))
        is_hole = hierarchy[i][3] != -1  # has a parent -> this is a hole
        # Force outer contours one way and holes the opposite way,
        # regardless of OpenCV's absolute contour-direction convention --
        # rasterizers only require holes to wind opposite their enclosing
        # outer contour under the nonzero fill rule.
        area_sign = signed_area(font_pts)
        want_negative = not is_hole  # outer contours: negative signed area (clockwise in y-up space); holes: positive
        if (area_sign < 0) != want_negative:
            font_pts = font_pts[::-1]

        shapes.append(font_pts)

    if not shapes:
        return None

    # The crop is the whole template box, so the ink can sit anywhere inside it.
    # Re-origin on the ink's own left edge, otherwise every glyph inherits the
    # box width as its advance and the font renders monospaced.
    ink_min_x = min(float(s[:, 0].min()) for s in shapes)
    ink_max_x = max(float(s[:, 0].max()) for s in shapes)
    shift = side_bearing - ink_min_x

    pen = TTGlyphPen(None)
    for font_pts in shapes:
        font_pts = font_pts + np.array([shift, 0.0])
        pen.qCurveTo(*[tuple(p) for p in font_pts], None)
        pen.closePath()

    glyph = pen.glyph()
    advance_width = int(round(ink_max_x - ink_min_x + 2 * side_bearing))
    return glyph, advance_width


def build_font(glyphs_dir, out_path, family, style="Regular"):
    with open(os.path.join(glyphs_dir, "manifest.json")) as f:
        manifest = json.load(f)

    glyph_order = [".notdef"]
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (UPM // 2, 0)}
    cmap = {}
    skipped = []
    default_width = int(UPM * 0.55)

    # --- single characters (cmap'd) ---
    for label, entry in manifest.items():
        if entry["is_pair"]:
            continue
        gname = glyph_name_for_char(label)
        if entry["empty"]:
            skipped.append(label)
            continue
        img = cv2.imread(os.path.join(glyphs_dir, entry["file"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            skipped.append(label)
            continue
        h, w = img.shape
        scale = UPM / h
        result = trace_glyph(img, scale, h * BASELINE_FRAC, SIDE_BEARING)
        if result is None:
            skipped.append(label)
            continue
        glyph, adv = result
        glyph_order.append(gname)
        glyphs[gname] = glyph
        metrics[gname] = (adv, SIDE_BEARING)
        cmap[ord(label)] = gname

    # space is handy to have even though the template doesn't capture it
    if 0x20 not in cmap:
        glyph_order.append("space")
        glyphs["space"] = TTGlyphPen(None).glyph()
        metrics["space"] = (default_width, 0)
        cmap[0x20] = "space"

    # --- ligatures (pairs; not in cmap, only reachable via GSUB) ---
    fea_lines = ["languagesystem DFLT dflt;", "languagesystem latn dflt;", "", "feature liga {"]
    n_ligatures = 0
    for label, entry in manifest.items():
        if not entry["is_pair"]:
            continue
        component_names = [glyph_name_for_char(c) for c in label]
        if entry["empty"]:
            skipped.append(label)
            continue
        if not all(c in cmap.values() or glyph_name_for_char(c) in glyphs for c in component_names):
            # a component single-letter glyph failed to vectorize; can't
            # safely reference it as a fallback and the ligature glyph
            # would be orphaned, so skip this ligature.
            missing = [c for c in component_names if c not in glyphs]
            if missing:
                skipped.append(f"{label} (ligature; missing base glyph(s) {missing})")
                continue
        img = cv2.imread(os.path.join(glyphs_dir, entry["file"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            skipped.append(label)
            continue
        h, w = img.shape
        scale = UPM / h
        result = trace_glyph(img, scale, h * BASELINE_FRAC, SIDE_BEARING)
        if result is None:
            skipped.append(label)
            continue
        glyph, adv = result
        gname = ligature_glyph_name(label)
        glyph_order.append(gname)
        glyphs[gname] = glyph
        metrics[gname] = (adv, SIDE_BEARING)
        fea_lines.append(f"    sub {' '.join(component_names)} by {gname};")
        n_ligatures += 1
    fea_lines.append("} liga;")

    if skipped:
        print(f"WARNING: skipped {len(skipped)} boxes (blank or unvectorizable): {skipped}", file=sys.stderr)

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupNameTable({
        "familyName": family,
        "styleName": style,
        "uniqueFontIdentifier": f"{family}-{style}",
        "fullName": f"{family} {style}",
        "psName": f"{family.replace(' ', '')}-{style}",
        "version": "Version 1.0",
    })
    fb.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT, usWinAscent=ASCENT, usWinDescent=-DESCENT)
    fb.setupPost()

    if n_ligatures:
        fea_text = "\n".join(fea_lines)
        try:
            from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
            addOpenTypeFeaturesFromString(fb.font, fea_text)
        except ImportError:
            import tempfile
            from fontTools.feaLib.builder import addOpenTypeFeatures
            with tempfile.NamedTemporaryFile("w", suffix=".fea", delete=False) as tmp:
                tmp.write(fea_text)
                tmp_path = tmp.name
            addOpenTypeFeatures(tmp_path, fb.font)
            os.unlink(tmp_path)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fb.font.save(out_path)
    print(f"Wrote {out_path}: {len(glyph_order)} glyphs "
          f"({len(cmap)} mapped characters, {n_ligatures} ligatures), {len(skipped)} skipped.")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glyphs", default="glyphs")
    ap.add_argument("--out", default="fonts/MyHandwriting.ttf")
    ap.add_argument("--family", default="My Handwriting")
    ap.add_argument("--style", default="Regular")
    args = ap.parse_args()
    build_font(args.glyphs, args.out, args.family, args.style)


if __name__ == "__main__":
    main()
