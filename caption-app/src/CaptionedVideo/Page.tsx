import { makeTransform, scale, translateY } from "@remotion/animation-utils";
import { TikTokPage } from "@remotion/captions";
import { fitText } from "@remotion/layout-utils";
import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { HandwritingFont } from "../load-font";

const fontFamily = HandwritingFont;

const container: React.CSSProperties = {
  justifyContent: "center",
  alignItems: "center",
  top: undefined,
  bottom: 120,
  height: 150,
};

// Tuning knobs -- restyle freely, this is a plain starting point.
const DESIRED_FONT_SIZE = 110;
const HIGHLIGHT_COLOR = "#f6c945";
const INK_COLOR = "#1a1a1a";

export const Page: React.FC<{
  readonly enterProgress: number;
  readonly page: TikTokPage;
}> = ({ enterProgress, page }) => {
  const frame = useCurrentFrame();
  const { width, fps } = useVideoConfig();
  const timeInMs = (frame / fps) * 1000;

  // No textTransform:"uppercase" here (unlike the stock TikTok template) --
  // a handwriting font only has glyphs for what you actually wrote, and
  // forcing caps would either miss your uppercase set entirely or throw
  // away the point of capturing upper/lowercase separately.
  const fittedText = fitText({
    fontFamily,
    text: page.text,
    withinWidth: width * 0.9,
  });

  const fontSize = Math.min(DESIRED_FONT_SIZE, fittedText.fontSize);

  return (
    <AbsoluteFill style={container}>
      <div
        style={{
          fontSize,
          color: INK_COLOR,
          // Ligatures ("th", "an", "ing"...) only apply if the font you
          // loaded actually has a GSUB 'liga' feature -- scripts/03_build_font.py
          // adds one automatically from the pair boxes you filled in.
          fontFeatureSettings: '"liga" 1, "dlig" 1',
          fontVariantLigatures: "common-ligatures",
          backgroundColor: "rgba(255,255,255,0.82)",
          padding: "10px 24px",
          borderRadius: 12,
          transform: makeTransform([
            scale(interpolate(enterProgress, [0, 1], [0.8, 1])),
            translateY(interpolate(enterProgress, [0, 1], [50, 0])),
          ]),
          fontFamily,
        }}
      >
        <span
          style={{
            transform: makeTransform([
              scale(interpolate(enterProgress, [0, 1], [0.8, 1])),
              translateY(interpolate(enterProgress, [0, 1], [50, 0])),
            ]),
          }}
        >
          {page.tokens.map((t, index) => {
            const startRelativeToSequence = t.fromMs - page.startMs;
            const endRelativeToSequence = t.toMs - page.startMs;

            const active =
              startRelativeToSequence <= timeInMs &&
              endRelativeToSequence > timeInMs;

            return (
              <span
                key={`${t.fromMs}-${index}`}
                style={{
                  display: "inline",
                  whiteSpace: "pre",
                  color: active ? HIGHLIGHT_COLOR : INK_COLOR,
                }}
              >
                {t.text}
              </span>
            );
          })}
        </span>
      </div>
    </AbsoluteFill>
  );
};
