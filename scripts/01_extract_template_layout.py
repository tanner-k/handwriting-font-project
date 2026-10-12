#!/usr/bin/env python3
"""
Parse the blank Handwriting Capture Template PDF and record, for every writing
box, its label (which character or letter-pair goes in it) and its rectangle
-- normalized to a 0..1 fraction of the page width/height so the layout is
resolution-independent. Also records the four black corner registration
squares, which 02_extract_glyphs.py uses to de-skew a photographed/scanned
copy of the filled-in sheet before cropping.

Run once against the known blank template:
    python3 scripts/01_extract_template_layout.py template/blank_template.pdf template/template_layout.json
"""
import collections
import json
import sys

import pdfplumber

# The exact label -> intended character(s) mapping, in reading order.
# Single characters map straight to a Unicode codepoint; the "pairs" section
# maps to a two-letter sequence that becomes a ligature glyph, not a cmap
# entry (you can never type a private-use codepoint for "th" -- you type
# t-h and the font's GSUB 'liga' feature substitutes the joined glyph).
UPPER_ROW1 = list("ABCDEFGHIJ")
UPPER_ROW2 = list("KLMNOPQRST")
UPPER_ROW3 = list("UVWXYZ") + ["0", "1", "2", "3"]
LOWER_ROW1 = list("abcdefghij")
LOWER_ROW2 = list("klmnopqrst")
LOWER_ROW3 = list("uvwxyz") + [".", ",", "!", "?"]
PAIR_ROW1 = ["th", "he", "in", "er", "an", "re", "on"]
PAIR_ROW2 = ["at", "en", "nd", "st", "or", "to", "is"]
PAIR_ROW3 = ["ee", "oo", "ll", "ss", "ff", "tt", "ing"]

ALL_LABELS = (
    UPPER_ROW1 + UPPER_ROW2 + UPPER_ROW3
    + LOWER_ROW1 + LOWER_ROW2 + LOWER_ROW3
    + PAIR_ROW1 + PAIR_ROW2 + PAIR_ROW3
)
PAIR_LABELS = set(PAIR_ROW1 + PAIR_ROW2 + PAIR_ROW3)

# Word-extraction is case-sensitive text matching; punctuation labels render
# as their literal character. Some labels collide in lowercase-with-itself
# (fine, we match by position, not just text) but a couple of single-char
# labels are ambiguous against pdfplumber's word splitting for punctuation
# (e.g. "." might not be picked up as its own word). We handle that by
# falling back to positional (row/column) assignment when text matching
# comes up short -- see match_labels_to_boxes().


def find_corner_squares(page):
    # Don't hardcode an absolute point size -- different PDF renderers
    # (a design tool's own export vs. a browser's @page print-to-PDF) can
    # rasterize the same "0.35in square" CSS box to different point sizes.
    # Instead, look for small, roughly-square filled rects (aspect ~1:1,
    # in a plausible registration-mark size window) and require exactly 4.
    candidates = [
        r for r in page.rects
        if 12 < (r["x1"] - r["x0"]) < 70 and 12 < (r["bottom"] - r["top"]) < 70
        and abs((r["x1"] - r["x0"]) - (r["bottom"] - r["top"])) < 4
    ]
    squares = candidates
    if len(squares) != 4:
        raise RuntimeError(
            f"expected 4 corner squares, found {len(squares)} candidates "
            f"(sizes: {[(round(r['x1']-r['x0']), round(r['bottom']-r['top'])) for r in candidates]})"
        )
    out = []
    for s in squares:
        cx = (s["x0"] + s["x1"]) / 2
        cy = (s["top"] + s["bottom"]) / 2
        out.append({"x": cx, "y": cy})
    return out


ROWS = [UPPER_ROW1, UPPER_ROW2, UPPER_ROW3, LOWER_ROW1, LOWER_ROW2, LOWER_ROW3, PAIR_ROW1, PAIR_ROW2, PAIR_ROW3]


def find_box_rects(page, corners):
    # Box interiors are filled rects roughly 46-90pt tall; hairline border
    # strips (drawn as separate 1pt-wide/tall filled rects), the two
    # full-page background fills, and the corner registration squares
    # (also ~33x33, which lands inside this size window) are excluded.
    corner_xy = {(round(c["x"]), round(c["y"])) for c in corners}

    def is_corner(r):
        cx = round((r["x0"] + r["x1"]) / 2)
        cy = round((r["top"] + r["bottom"]) / 2)
        return any(abs(cx - x) < 3 and abs(cy - y) < 3 for x, y in corner_xy)

    boxes = [
        r for r in page.rects
        if 10 < (r["x1"] - r["x0"]) < 200 and 10 < (r["bottom"] - r["top"]) < 120
        and not is_corner(r)
    ]
    # De-duplicate near-identical overlapping rects (some templates draw a
    # box body twice, e.g. a fill + a hover/hit-area rect).
    dedup = []
    for r in boxes:
        box = (r["x0"], r["top"], r["x1"], r["bottom"])
        if any(
            abs(box[0] - b[0]) < 2 and abs(box[1] - b[1]) < 2
            and abs(box[2] - b[2]) < 2 and abs(box[3] - b[3]) < 2
            for b in dedup
        ):
            continue
        dedup.append(box)
    return dedup


def match_labels_to_boxes(box_rects):
    # Cluster box rects into rows by their (rounded) top coordinate, sort
    # each row left-to-right, then zip against the known reading order of
    # labels for that row. This is robust against PDF text-extraction
    # quirks (word splitting, case collisions between a box label and
    # ordinary prose like "the"/"AS"/"ONE" elsewhere on the page) because
    # it never looks at text at all -- only geometry, plus the fixed grid
    # order the template generator itself uses.
    row_groups = collections.defaultdict(list)
    for r in box_rects:
        key = round(r[1] / 5) * 5  # bucket by top, tolerant of sub-pixel jitter
        row_groups[key].append(r)

    sorted_row_keys = sorted(row_groups.keys())
    if len(sorted_row_keys) != len(ROWS):
        raise RuntimeError(
            f"expected {len(ROWS)} box rows, found {len(sorted_row_keys)} "
            f"(row sizes: {[len(row_groups[k]) for k in sorted_row_keys]})"
        )

    assignments = []
    for key, expected_labels in zip(sorted_row_keys, ROWS):
        row_boxes = sorted(row_groups[key], key=lambda r: r[0])
        if len(row_boxes) != len(expected_labels):
            raise RuntimeError(
                f"row at top~{key} has {len(row_boxes)} boxes, "
                f"expected {len(expected_labels)} for labels {expected_labels}"
            )
        for label, box in zip(expected_labels, row_boxes):
            assignments.append((label, box))
    return assignments


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "template/blank_template.pdf"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "template/template_layout.json"

    pdf = pdfplumber.open(pdf_path)
    page = pdf.pages[0]
    W, H = page.width, page.height

    corners = find_corner_squares(page)
    box_rects = find_box_rects(page, corners)
    assignments = match_labels_to_boxes(box_rects)

    found_labels = {text for text, _ in assignments}
    expected = set(ALL_LABELS)
    missing = [l for l in ALL_LABELS if l not in found_labels]
    if missing:
        print(f"WARNING: {len(missing)} labels did not auto-match a box: {missing}", file=sys.stderr)

    by_label = {}
    for text, (x0, top, x1, bottom) in assignments:
        if text in by_label:
            continue  # keep first match if a label text repeats
        by_label[text] = (x0, top, x1, bottom)

    boxes_out = []
    for label in ALL_LABELS:
        if label not in by_label:
            continue
        x0, top, x1, bottom = by_label[label]
        boxes_out.append({
            "label": label,
            "is_pair": label in PAIR_LABELS,
            # normalized 0..1 fractions of page size, independent of DPI
            "x0": x0 / W,
            "y0": top / H,
            "x1": x1 / W,
            "y1": bottom / H,
        })

    layout = {
        "page_width_pt": W,
        "page_height_pt": H,
        "corner_marks_pt": corners,  # in original PDF point space, for reference
        "corner_marks_norm": [{"x": c["x"] / W, "y": c["y"] / H} for c in corners],
        "boxes": boxes_out,
    }

    with open(out_path, "w") as f:
        json.dump(layout, f, indent=2)

    print(f"Wrote {len(boxes_out)}/{len(ALL_LABELS)} boxes and {len(corners)} corner marks to {out_path}")
    if len(boxes_out) != len(ALL_LABELS):
        missing2 = [l for l in ALL_LABELS if l not in by_label]
        print(f"MISSING: {missing2}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
