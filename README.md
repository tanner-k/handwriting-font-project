# Handwriting -> Font -> Captioned Video

Turns your own handwriting into a real font (with OpenType ligatures for
"th", "an", "ing", etc.), then uses that font to caption a video, timed to
the audio via Whisper.

Nothing here needs FontForge or the `potrace` binary -- both would normally
be the standard tools for this, but installing either needs `apt`, and this
sandbox's network policy blocks package-repo access. Everything is instead
built with `fontTools` + OpenCV directly (pure Python, pip-installable
anywhere). The caption side is an adapted copy of Remotion's own official
`template-tiktok`, not something built from scratch.

## What's in here

```
template/
  blank_template.pdf       -- print this (corrected to a proper 8.5x11in
                               page -- see note below)
  source_template.html     -- the HTML this PDF is rendered from
  template_layout.json     -- box positions, extracted automatically

scripts/
  01_extract_template_layout.py  -- (already run once; re-run only if you edit the template)
  02_extract_glyphs.py           -- photo/scan -> de-skewed, cropped glyph PNGs
  03_build_font.py               -- glyph PNGs -> MyHandwriting.ttf, with ligatures
  _dry_run_synthetic_test.py     -- end-to-end pipeline test using synthetic
                                     stand-in glyphs (see "What's been verified" below)

run_font_pipeline.sh       -- runs steps 02+03 and drops the result into caption-app/

caption-app/                -- Remotion project (adapted from remotion-dev/template-tiktok)
  public/handwriting.ttf    -- PLACEHOLDER right now -- replace with your real font
  public/sample-video.mp4   -- Remotion's stock sample clip, for a first test render
  public/sample-video.json  -- fake captions.json I wrote by hand, matching that clip,
                               for testing the caption rendering before you have real
                               Whisper output
  src/load-font.ts          -- font family name + filename
  src/CaptionedVideo/Page.tsx -- caption styling (colors, size, highlight) -- restyle freely
  sub.mjs                   -- transcribes a video with whisper.cpp -> captions.json
```

## About the template PDF

The PDF you originally sent me was rendered onto an oversized ~26in x 15in
canvas with the actual template crammed into the top-left corner -- fine
for the pipeline (it uses normalized coordinates either way), but wasteful
if you print it, and it could confuse a printer's own "fit to page" step.
Since you also sent me the HTML source, I re-rendered `blank_template.pdf`
as a correct single 8.5x11in page and rebuilt `template_layout.json` against
that version. Print the one in this folder, not any older copy you may
already have.

## Step-by-step

**1. Install the Python dependencies** (once):
```
pip install -r requirements.txt
```

**2. Print `template/blank_template.pdf`.** Fill every box with a black
felt-tip pen (not ballpoint -- it vectorizes much more cleanly), without
touching the box borders. It's fine to leave a box blank if you don't want
a particular ligature or character; the pipeline detects and skips empty
boxes automatically (you'll get a warning listing which ones).

**3. Photograph or scan the filled sheet.** Even lighting, and make sure
all 4 solid black corner squares are fully visible -- they're the
registration marks the alignment step uses to correct for skew/perspective.

**4. Run the pipeline:**
```
./run_font_pipeline.sh path/to/your/photo.jpg
```
This crops every glyph, vectorizes it, builds `fonts/MyHandwriting.ttf`
(with the "th"/"an"/"ing"/etc. pairs compiled in as real OpenType ligatures,
GSUB `liga` feature), and copies it into `caption-app/public/handwriting.ttf`.

Check `glyphs/_debug_rectified.png` afterward -- the red box outlines should
land exactly on what you wrote. If they're off, the photo likely needs
better lighting or a squarer angle; retake it and rerun.

**5. Set up the Remotion app** (this needs a real internet connection --
this sandbox's network policy blocks npm's registry, so I couldn't run this
part here; see "What's been verified" below):
```
cd caption-app
npm install
npm run dev          # opens Remotion Studio -- lets you preview immediately
```
With just steps 1-4 done and `npm install` run, `npm run dev` will already
show your handwriting rendering the fake `sample-video.json` captions over
Remotion's stock sample clip -- a good first check before touching your
real video.

**6. Caption your real video:**
```
cp /path/to/your-video.mp4 public/
node sub.mjs public/your-video.mp4
```
This downloads Whisper.cpp and a speech model on first run (see
`whisper-config.mjs` for model choice -- bigger models are slower but more
accurate), transcribes the audio, and writes `public/your-video.json`.

Point the composition at it -- either edit the `src` in `src/Root.tsx`'s
`defaultProps`, or pass `--props='{"src":"public/your-video.mp4"}'` on the
render command below.

**7. Render:**
```
npx remotion render CaptionedVideo out.mp4
```

## Restyling the captions

`src/CaptionedVideo/Page.tsx` controls font size, ink color, the active-word
highlight color, and the background card behind the text -- all plain CSS
constants near the top of the file. I removed the stock template's
`textTransform: uppercase` and thick black outline stroke (a handwriting
font doesn't read well force-capitalized or outlined), but everything is a
simple starting point, not a fixed design.

Ligatures depend on `fontFeatureSettings: '"liga" 1'` in that same file --
already wired up. They'll only actually join two letters if you didn't
leave that pair's box blank on the template.

## What's been verified vs. what hasn't

**Verified, in this sandbox, against synthetic stand-in "handwriting":**
- The whole geometry pipeline: corner-square detection, perspective
  correction, box cropping -- tested against a deliberately skewed/warped
  synthetic photo, and it recovered a perfectly aligned page.
- Empty-box detection (deliberately blank boxes were correctly identified
  and skipped, not silently mis-rendered).
- Vectorization + hole winding (letters like "o"/"a" get real counters, not
  filled-in blobs -- checked with an explicit nonzero-winding-rule test,
  not just eyeballing).
- The compiled font's OpenType ligature substitutions (GSUB `liga`) --
  checked both programmatically (correct rule count) and visually, by
  loading the font in real Chromium via `@font-face` and rendering
  "the cat sat on a mat" with ligatures on vs. off side-by-side.
- The `caption-app` TSX edits are syntax-checked with `tsc`.

**Not run in this sandbox:** an actual `npm install` / `remotion render` --
this environment's network policy returns 403 on `registry.npmjs.org`
specifically (GitHub and PyPI are reachable, npm's registry isn't). The
`caption-app` code is a narrow, deliberate edit of Remotion's own official,
maintained `template-tiktok` example -- I read its real source before
changing anything, not the other way around -- but you'll be the first to
actually run it. Steps 5-7 above are ordinary `npm`/Remotion commands; if
something doesn't work, the most likely spot is a Remotion API detail that
shifted since I read the source, not the font/ligature machinery, which
*was* verified.
