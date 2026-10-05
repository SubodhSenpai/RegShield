// The website's docs are the repository's docs/*.md files, rendered at build time,
// so the site and GitHub always show the same text.

import fs from 'node:fs';
import path from 'node:path';
import { Marked } from 'marked';
import { escapeHtml, highlightHtml, languageOf } from './highlight';
import { withRelease } from './release';
import { REPO } from './site';

const RAW = 'https://raw.githubusercontent.com/SubodhSenpai/RegShield/main';
const DOCS_DIR = path.join(process.cwd(), '..', 'docs');

export const DOCS = [
  {
    slug: 'getting-started', file: 'getting-started.md', title: 'Getting started', href: '/docs',
    description: 'Install RegShield, write a scenario, evaluate an AI agent trace, and fail CI when the agent regresses.',
  },
  {
    slug: 'cookbook', file: 'cookbook.md', title: 'Cookbook', href: '/cookbook',
    description: 'Short recipes for testing AI agents: tool order, approvals, arguments, loops, multi-agent handoffs, graphs and CI, each with real output.',
  },
  {
    slug: 'patterns', file: 'patterns.md', title: 'Agentic patterns', href: '/docs/patterns',
    description: 'Checks for policy rules, human approval, plan-and-execute, multi-agent handoffs and loops, routing, parallel calls, graph workflows and reflection loops.',
  },
  {
    slug: 'integrations', file: 'integrations.md', title: 'Integrations', href: '/docs/integrations',
    description: 'Record LangChain, LangGraph and smolagents agents, any Python agent loop, or any language over REST, and evaluate the trace.',
  },
  {
    slug: 'production', file: 'production.md', title: 'In production', href: '/docs/production',
    description: 'Block risky AI agent actions as they happen, record OpenAI, Anthropic and Gemini SDK calls without code changes, export runs to OpenTelemetry, and keep model prices current.',
  },
  {
    slug: 'local-models', file: 'local-models.md', title: 'Local and self-hosted models', href: '/docs/local-models',
    description: 'Install Ollama and run AI agents and the RegShield LLM judge on your own GPU or servers (vLLM, LM Studio, llama.cpp), with or without paid APIs.',
  },
  {
    slug: 'reference', file: 'reference.md', title: 'Reference', href: '/docs/reference',
    description: 'Every RegShield scenario field, the trace and report formats, the classical algorithm behind each check, CLI flags, REST API and environment variables.',
  },
];

const ROUTES = Object.fromEntries(DOCS.map((doc) => [doc.file, doc.href]));
ROUTES['README.md'] = '/docs';

// GitHub's heading anchors: lowercase, punctuation dropped, spaces to hyphens
export function slugify(text) {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .trim()
    .replace(/\s/g, '-');
}

function plainText(markdown) {
  return markdown.replace(/`([^`]*)`/g, '$1').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_]{1,2}([^*_]+)[*_]{1,2}/g, '$1');
}

// Links between docs point at the site's pages; other repository files at GitHub
function resolveHref(href) {
  if (/^(?:[a-z]+:|#|\/)/i.test(href)) return href;
  const [file, hash] = href.split('#');
  const anchor = hash ? `#${hash}` : '';
  if (ROUTES[file]) return ROUTES[file] + anchor;
  const repoPath = path.posix.normalize(path.posix.join('docs', file));
  const kind = repoPath.endsWith('.md') && !repoPath.endsWith('README.md') ? 'blob' : 'tree';
  return `${REPO}/${kind}/main/${repoPath.replace(/README\.md$/, '')}${anchor}`;
}

function render(markdown) {
  const headings = [];
  const seen = new Map();
  const marked = new Marked({
    gfm: true,
    renderer: {
      heading({ tokens, depth, text }) {
        const base = slugify(plainText(text));
        const count = seen.get(base) || 0;
        seen.set(base, count + 1);
        const id = count ? `${base}-${count}` : base;
        const html = this.parser.parseInline(tokens);
        if (depth === 2 || depth === 3) headings.push({ id, depth, text: plainText(text) });
        if (depth === 1) return `<h1>${html}</h1>\n`;
        return `<h${depth} id="${id}"><a class="anchor" href="#${id}" aria-hidden="true">#</a>${html}</h${depth}>\n`;
      },
      code({ text, lang }) {
        const language = languageOf(lang);
        const label = language === 'output' ? (lang === 'console' ? 'shell' : 'output') : language === 'plain' ? 'text' : language;
        return (
          `<div class="code${language === 'output' ? ' is-output' : ''}">` +
          `<div class="code-bar"><span>${escapeHtml(label)}</span><button type="button" class="copy" data-copy>copy</button></div>` +
          `<pre><code>${highlightHtml(text, lang)}</code></pre></div>\n`
        );
      },
      link({ href, title, tokens }) {
        const target = resolveHref(href);
        const external = /^https?:/.test(target);
        const attrs = external ? ' target="_blank" rel="noreferrer"' : '';
        const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
        return `<a href="${escapeHtml(target)}"${titleAttr}${attrs}>${this.parser.parseInline(tokens)}</a>`;
      },
      image({ href, text }) {
        // docs/images/ is served at /docs-images/ (app/docs-images); anything else comes from GitHub
        let src = href;
        if (!/^(?:[a-z]+:|\/)/i.test(href)) {
          const repoPath = path.posix.normalize(path.posix.join('docs', href));
          src = repoPath.startsWith('docs/images/') ? `/docs-images/${repoPath.slice('docs/images/'.length)}` : `${RAW}/${repoPath}`;
        }
        return `<img src="${escapeHtml(src)}" alt="${escapeHtml(text)}" loading="lazy" class="doc-image">`;
      },
    },
  });
  // Wide tables scroll sideways on small screens instead of stretching the page
  const html = marked.parse(markdown).replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, '</table></div>');
  return { html, headings };
}

// With the latest release (lib/release.js), the doc's install links point at it
export function loadDoc(slug, release) {
  const doc = DOCS.find((d) => d.slug === slug);
  if (!doc) return null;
  let markdown = fs.readFileSync(path.join(DOCS_DIR, doc.file), 'utf-8');
  if (release) markdown = withRelease(markdown, release);
  return { ...doc, ...render(markdown), markdown };
}

// Page metadata for a doc: its own title, description, canonical URL and social card
export function docMetadata(doc) {
  return {
    title: doc.title,
    description: doc.description,
    alternates: { canonical: doc.href },
    openGraph: { type: 'article', title: `${doc.title} · RegShield`, description: doc.description, url: doc.href },
  };
}
