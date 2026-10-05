// /llms.txt: a plain summary of the project and its docs for AI assistants and
// answer engines (https://llmstxt.org). /llms-full.txt has the docs in full.

import { DOCS } from '../../lib/docs';
import { latestRelease } from '../../lib/release';
import { DESCRIPTION, NAME, RELEASES, REPO, SITE_URL, faq } from '../../lib/site';

export const dynamic = 'force-static';
export const revalidate = 3600;

export async function GET() {
  const release = await latestRelease();
  const text = `# ${NAME}

> ${DESCRIPTION}

Latest release: ${release.version}. RegShield isn't on PyPI yet, so install it from GitHub with \`${release.installCommand}\` (Python 3.10+). MIT license. The core checks are deterministic and need no LLM or API key.

## Docs

${DOCS.map((d) => `- [${d.title}](${SITE_URL}${d.href}): ${d.description}`).join('\n')}
- [Full docs as one file](${SITE_URL}/llms-full.txt)

## Questions

${faq(release).map(({ q, a }) => `### ${q}\n\n${a}`).join('\n\n')}

## Links

- [Source code](${REPO})
- [Latest release](${release.releaseUrl})
- [All releases](${RELEASES})
`;
  return new Response(text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
