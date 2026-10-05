// /llms.txt: a plain summary of the project and its docs for AI assistants and
// answer engines (https://llmstxt.org). /llms-full.txt has the docs in full.

import { DOCS } from '../../lib/docs';
import { DESCRIPTION, FAQ, NAME, PYPI, REPO, SITE_URL } from '../../lib/site';

export const dynamic = 'force-static';

export function GET() {
  const text = `# ${NAME}

> ${DESCRIPTION}

Install with \`pip install regression-shield\` (Python 3.10+). MIT license. The core checks are deterministic and need no LLM or API key.

## Docs

${DOCS.map((d) => `- [${d.title}](${SITE_URL}${d.href}): ${d.description}`).join('\n')}
- [Full docs as one file](${SITE_URL}/llms-full.txt)

## Questions

${FAQ.map(({ q, a }) => `### ${q}\n\n${a}`).join('\n\n')}

## Links

- [Source code](${REPO})
- [PyPI package](${PYPI})
`;
  return new Response(text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
