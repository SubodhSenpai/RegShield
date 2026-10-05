// Serves the repository's docs/images/ at /docs-images/, so the docs and the site
// share one copy of each screenshot. Every file is written out at build time.

import fs from 'node:fs';
import path from 'node:path';

const DIR = path.join(process.cwd(), '..', 'docs', 'images');
const TYPES = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml' };

export const dynamic = 'force-static';
export const dynamicParams = false;

export function generateStaticParams() {
  return fs.readdirSync(DIR).filter((file) => TYPES[path.extname(file).slice(1).toLowerCase()]).map((file) => ({ file }));
}

export async function GET(_request, { params }) {
  const { file } = await params;
  const name = path.basename(file);
  return new Response(fs.readFileSync(path.join(DIR, name)), {
    headers: { 'Content-Type': TYPES[path.extname(name).slice(1).toLowerCase()] },
  });
}
