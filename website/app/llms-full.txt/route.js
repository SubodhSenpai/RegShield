// /llms-full.txt: every doc page as Markdown in one file, for AI assistants.

import { DOCS, loadDoc } from '../../lib/docs';
import { latestRelease } from '../../lib/release';
import { DESCRIPTION, NAME } from '../../lib/site';

export const dynamic = 'force-static';
export const revalidate = 3600;

export async function GET() {
  const release = await latestRelease();
  const docs = DOCS.map((d) => loadDoc(d.slug, release).markdown.trim()).join('\n\n---\n\n');
  return new Response(`# ${NAME}\n\n> ${DESCRIPTION}\n\n---\n\n${docs}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
