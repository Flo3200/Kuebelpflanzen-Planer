// Subtle botanical line drawings (own SVG, no external images). Colour and opacity come from tokens.
import type { CSSProperties } from "react";

type Variant = "fern" | "leaf" | "olive" | "citrus";

function fern(): string[] {
  const paths: string[] = ["M100 390 C 96 300, 92 200, 120 20"];
  for (let i = 0; i < 16; i++) {
    const tpos = i / 16;
    const y = 370 - tpos * 340;
    const x = 100 - Math.sin(tpos * 1.2) * 4 + tpos * 20 - (tpos > 0.8 ? (tpos - 0.8) * 20 : 0);
    const len = 70 * (1 - tpos * 0.75);
    const lift = 18 + tpos * 10;
    paths.push(`M${x} ${y} q ${-len * 0.55} ${-lift * 0.2} ${-len} ${-lift}`);
    paths.push(`M${x} ${y} q ${len * 0.55} ${-lift * 0.2} ${len} ${-lift}`);
    for (let k = 1; k < 4; k++) {
      const f = k / 4;
      const lx = x - len * f;
      const ly = y - lift * f * f;
      const rx = x + len * f;
      paths.push(`M${lx} ${ly} l ${-6 * (1 - f)} ${-8 * (1 - f) - 2}`);
      paths.push(`M${rx} ${ly} l ${6 * (1 - f)} ${-8 * (1 - f) - 2}`);
    }
  }
  return paths;
}

function leaf(): string[] {
  const p = [
    "M20 380 C 60 260, 120 120, 300 40 C 300 160, 220 300, 20 380 Z",
    "M20 380 C 110 280, 200 160, 300 40",
  ];
  for (let i = 1; i < 9; i++) {
    const f = i / 9;
    const x = 20 + 280 * f;
    const y = 380 - 340 * f + Math.sin(f * Math.PI) * 30;
    p.push(`M${x} ${y} q ${-30 + f * 10} ${-20} ${-40 + f * 25} ${-60 + f * 20}`);
    p.push(`M${x} ${y} q ${25} ${10} ${55 - f * 25} ${20 - f * 10}`);
  }
  return p;
}

function olive(): string[] {
  const p = ["M10 300 C 120 250, 240 180, 390 60"];
  const leaves = [
    [60, 278, -1], [95, 262, 1], [130, 243, -1], [165, 225, 1], [200, 203, -1], [235, 182, 1], [270, 158, -1],
    [305, 133, 1], [340, 104, -1], [370, 78, 1],
  ];
  for (const [x, y, s] of leaves) {
    const dx = 46;
    const dy = s * 34;
    p.push(`M${x} ${y} C ${x + dx * 0.3} ${y + dy * 0.6 - 10}, ${x + dx * 0.8} ${y + dy * 0.9}, ${x + dx} ${y + dy}`);
    p.push(`M${x} ${y} C ${x + dx * 0.5} ${y + dy * 0.2}, ${x + dx * 0.9} ${y + dy * 0.6 - 4}, ${x + dx} ${y + dy}`);
  }
  p.push("M150 236 m -9 0 a 9 12 20 1 0 18 0 a 9 12 20 1 0 -18 0");
  p.push("M252 172 m -8 0 a 8 11 -20 1 0 16 0 a 8 11 -20 1 0 -16 0");
  return p;
}

function citrus(): string[] {
  const p = ["M20 380 C 90 300, 150 220, 230 60"];
  const leaves = [
    [70, 320, -1], [100, 280, 1], [140, 220, -1], [170, 170, 1], [205, 110, -1],
  ];
  for (const [x, y, s] of leaves) {
    const dx = s * 70;
    p.push(`M${x} ${y} C ${x + dx * 0.4} ${y - 40}, ${x + dx} ${y - 30}, ${x + dx * 1.15} ${y - 10} C ${x + dx * 0.8} ${y + 10}, ${x + dx * 0.3} ${y + 5}, ${x} ${y}`);
    p.push(`M${x} ${y} L ${x + dx} ${y - 18}`);
  }
  p.push("M250 200 m -38 0 a 38 32 -25 1 0 76 0 a 38 32 -25 1 0 -76 0");
  p.push("M218 170 q 6 -10 14 -8");
  return p;
}

const DRAWINGS: Record<Variant, { viewBox: string; paths: () => string[] }> = {
  fern: { viewBox: "0 0 240 400", paths: fern },
  leaf: { viewBox: "0 0 320 400", paths: leaf },
  olive: { viewBox: "0 0 400 320", paths: olive },
  citrus: { viewBox: "0 0 320 400", paths: citrus },
};

export function Botanical({ variant, style, strokeWidth = 1.4 }: { variant: Variant; style?: CSSProperties; strokeWidth?: number }) {
  const d = DRAWINGS[variant];
  return (
    <svg className="botanical" viewBox={d.viewBox} style={style} aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
        {d.paths().map((path, i) => (
          <path key={i} d={path} />
        ))}
      </g>
    </svg>
  );
}
