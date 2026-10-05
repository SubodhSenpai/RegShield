// /llms-full.txt: every doc page as Markdown in one file, for AI assistants.

import { DOCS, loadDoc } from '../../lib/docs';
import { DESCRIPTION, NAME } from '../../lib/site';

export const dynamic = 'force-static';

export function GET() {
  const docs = DOCS.map((d) => loadDoc(d.slug).markdown.trim()).join('\n\n---\n\n');
  return new Response(`# ${NAME}\n\n> ${DESCRIPTION}\n\n---\n\n${docs}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
