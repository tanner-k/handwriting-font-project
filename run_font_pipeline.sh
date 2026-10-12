#!/usr/bin/env bash
# Runs the crop -> vectorize -> font-build stages against a photo/scan of
# your filled-in template, then drops the result into caption-app/public/
# so the Remotion project picks it up automatically.
#
# Usage: ./run_font_pipeline.sh path/to/your/photo.jpg ["Font Family Name"]
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <photo_or_scan.jpg> [\"Font Family Name\"]" >&2
  exit 1
fi

PHOTO="$1"
FAMILY="${2:-My Handwriting}"

python3 scripts/02_extract_glyphs.py "$PHOTO" --layout template/template_layout.json --out glyphs
echo
echo "Check glyphs/_debug_rectified.png now -- the red box outlines should"
echo "sit exactly on your written boxes. If they don't, retake the photo"
echo "(even lighting, all 4 corner squares visible) before continuing."
echo

python3 scripts/03_build_font.py --glyphs glyphs --out fonts/MyHandwriting.ttf --family "$FAMILY"

mkdir -p caption-app/public
cp fonts/MyHandwriting.ttf caption-app/public/handwriting.ttf
echo
echo "Copied the font into caption-app/public/handwriting.ttf."
echo "If you changed the family name, update HandwritingFont in"
echo "caption-app/src/load-font.ts to match: \"$FAMILY\""
