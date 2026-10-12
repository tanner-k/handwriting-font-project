import { continueRender, delayRender, staticFile } from "remotion";

// Swap in the font produced by scripts/03_build_font.py: copy the .ttf into
// public/ under this name (or change the filename below), and set the
// family name to match --family from that script.
export const HandwritingFont = `Tanner Handwriting`;
const FONT_FILE = "handwriting.ttf";

let loaded = false;

export const loadFont = async (): Promise<void> => {
  if (loaded) {
    return Promise.resolve();
  }

  const waitForFont = delayRender();

  loaded = true;

  const font = new FontFace(
    HandwritingFont,
    `url('${staticFile(FONT_FILE)}') format('truetype')`,
  );

  await font.load();
  document.fonts.add(font);

  continueRender(waitForFont);
};
