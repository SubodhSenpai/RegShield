'use client';

// A dusk landscape drawn in text: a few stars, a sun setting behind the hills,
// a warm haze on the horizon and three ridges, the nearest with trees.
// One scene sits behind the whole site. The same input always draws the same
// picture, so the server's HTML and the browser agree. It's a client component
// so the picture isn't sent twice (once as HTML, once as React data).

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';

const COLS = 300;
const ROWS = 60;
const ASPECT = 0.514; // a character cell is about half as wide as it is tall

// Deterministic noise in [0, 1) for a cell
function hash(x, y) {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

const RIDGES = [
  // far, middle, near: height as a share of the rows, amplitude, three sine waves, texture
  { base: 0.6, amp: 0.2, waves: [[0.021, 0.3], [0.057, 1.7], [0.14, 4.1]], chars: '::.', density: 0.72 },
  { base: 0.72, amp: 0.13, waves: [[0.016, 2.1], [0.043, 0.4], [0.11, 3.3]], chars: '=-+:', density: 0.8 },
  { base: 0.87, amp: 0.09, waves: [[0.012, 4.4], [0.035, 2.2], [0.09, 0.9]], chars: '#%*=', density: 0.88 },
];

function ridgeRow(layer, x) {
  const { base, amp, waves } = RIDGES[layer];
  // Ridged waves give peaks rather than rolling hills
  const wave = waves.reduce((sum, [f, p], i) => sum + [0.62, 0.28, 0.1][i] * (1 - 2 * Math.abs(Math.sin(x * f + p))), 0);
  // Mountains rise toward the edges and leave a valley in the middle for the text
  const edge = Math.min(1, Math.abs(x - COLS / 2) / (COLS * 0.32));
  return ROWS * (base - amp * (0.25 + 0.75 * edge) * (wave + 0.35));
}

const SUN = { x: COLS * 0.74, y: ROWS * 0.5, r: ROWS * 0.105 };
const SUN_SHADES = '@@%%##**+=';

function sunDistance(x, y) {
  return Math.hypot((x - SUN.x) * ASPECT, y - SUN.y) / SUN.r;
}

function skyCell(x, y, farTop) {
  const d = sunDistance(x, y);
  if (d < 1) {
    const shade = SUN_SHADES[Math.min(SUN_SHADES.length - 1, Math.floor(d * d * SUN_SHADES.length))];
    return [shade, d < 0.6 ? 's1' : 's2'];
  }
  const h = hash(x, y);
  // Haze: thickest just above the hills and near the sun
  const above = farTop - y;
  const near = Math.max(0, 1 - Math.abs(x - SUN.x) / 110);
  const haze = above > 0 && above < 11 ? (1 - above / 11) * (0.18 + 0.55 * near) : 0;
  if (d < 1.9 && h < 0.5 * (1 - (d - 1) / 0.9)) return [h < 0.15 ? ':' : '.', 'g'];
  if (h < haze) return [hash(y, x) < 0.3 ? ':' : '.', near > 0.55 ? 'g' : 'h'];
  if (h > 0.992) return ['.', y < ROWS * 0.3 ? 'k1' : 'k2'];
  return [' ', ''];
}

function outlineChar(layer, x, row) {
  if (Math.floor(ridgeRow(layer, x + 1)) < row) return '/';
  if (Math.floor(ridgeRow(layer, x - 1)) < row) return '\\';
  return '_';
}

function buildGrid() {
  const grid = Array.from({ length: ROWS }, () => Array.from({ length: COLS }, () => [' ', '']));
  for (let x = 0; x < COLS; x++) {
    const tops = RIDGES.map((_, layer) => Math.floor(ridgeRow(layer, x)));
    // The side of the scene nearer the sun catches more light
    const lit = Math.max(0, 1 - Math.abs(x - SUN.x) / 90);
    for (let y = 0; y < ROWS; y++) {
      let layer = -1; // the nearest ridge whose top is at or above this row owns the cell
      for (let l = RIDGES.length - 1; l >= 0; l--) {
        if (y >= tops[l]) { layer = l; break; }
      }
      if (layer < 0) {
        grid[y][x] = skyCell(x, y, tops[0]);
      } else if (y === tops[layer]) {
        grid[y][x] = [outlineChar(layer, x, y), `o${layer}`];
      } else {
        const { chars, density } = RIDGES[layer];
        const depth = y - tops[layer];
        if (hash(x + layer * 997, y) < density) {
          const ch = chars[Math.floor(hash(y * 3, x) * chars.length)];
          // Slopes just under the ridge line, on the sun's side, are lit
          grid[y][x] = [ch, depth < 3 && hash(x, y + 7) < lit ? `l${layer}` : `f${layer}`];
        }
      }
    }
    // Trees on the near ridge, and a few smaller ones on the middle ridge
    for (const [layer, chance] of [[1, 0.05], [2, 0.16]]) {
      const top = tops[layer];
      const hidden = tops.slice(layer + 1).some((t) => t <= top - 1);
      if (hidden || top < 3 || hash(x * 7 + layer, layer) >= chance) continue;
      grid[top - 1][x] = ['^', `t${layer}`];
      if (layer === 2 && hash(x, 99) < 0.45) grid[top - 2][x] = ['^', `t${layer}`];
    }
  }
  return grid;
}

// Rows as [text, className] runs, so the page renders a few thousand spans
// rather than one element per character
const RUNS = buildGrid().map((row) => {
  const runs = [];
  for (const [ch, cls] of row) {
    const last = runs[runs.length - 1];
    if (last && last[1] === cls) last[0] += ch;
    else runs.push([ch, cls]);
  }
  return runs;
});

export default function Landscape() {
  const pathname = usePathname();

  // Full strength while the landing page's first screen is in view; dimmed once
  // it scrolls away, so the scene doesn't compete with the text (see globals.css)
  useEffect(() => {
    const hero = document.querySelector('.hero');
    const root = document.documentElement;
    if (!hero) return undefined;
    const observer = new IntersectionObserver(([entry]) => {
      root.dataset.scene = entry.intersectionRatio > 0.35 ? 'full' : 'quiet';
    }, { threshold: [0, 0.35, 1] });
    observer.observe(hero);
    return () => {
      observer.disconnect();
      delete root.dataset.scene;
    };
  }, [pathname]);

  return (
    <pre className="landscape" aria-hidden="true">
      {RUNS.map((runs, y) => (
        <span key={y}>
          {runs.map(([text, cls], i) => (cls ? <span key={i} className={cls}>{text}</span> : text))}
          {'\n'}
        </span>
      ))}
    </pre>
  );
}
