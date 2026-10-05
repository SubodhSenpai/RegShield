// Site-wide facts used by metadata, structured data, the sitemap and llms.txt.
// The version and the install command come from the latest GitHub release (lib/release.js).

// Set SITE_URL when deploying (e.g. https://regshield.example.com). On Vercel the
// production domain is picked up automatically.
export const SITE_URL = (
  process.env.SITE_URL ||
  (process.env.VERCEL_PROJECT_PRODUCTION_URL && `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`) ||
  'http://localhost:3000'
).replace(/\/$/, '');

export const NAME = 'RegShield';
export const REPO = 'https://github.com/SubodhSenpai/RegShield';
export const RELEASES = `${REPO}/releases`;
export const TITLE = 'RegShield: regression tests for AI agents';
export const DESCRIPTION =
  'Open-source Python library that tests AI agents by their tool calls, with classical algorithms and an optional LLM judge. Offline, in pytest or CI.';

const QUESTIONS = [
  {
    q: 'What is RegShield?',
    a: 'An open-source Python library (MIT) for regression testing AI agents. It checks which tools ran, in what order, with which arguments and approvals, against rules you write once.',
  },
  {
    q: 'How is it different from LLM evals?',
    a: 'Most evals ask another LLM to grade the final answer. RegShield checks the actions behind it with classical algorithms, such as graph cycle detection and partial-order checks, offline and with no API key. An optional LLM judge catches what rules cannot, like a wrong amount.',
  },
  {
    q: 'Which agent frameworks does it work with?',
    a: 'LangChain, LangGraph, smolagents, raw OpenAI, Anthropic and Gemini SDK loops, any Python loop through TraceRecorder, and any language over REST.',
  },
  {
    q: 'Does it send my data anywhere?',
    a: 'No. The checks and dashboard run on your machine. Network calls happen only for what you turn on: the LLM judge, exporting runs, or refreshing prices.',
  },
  {
    q: 'How do I run it in CI?',
    a: 'Call raise_for_failures() in a pytest test, or run regshield eval scenarios.json, which exits with 1 when a scenario fails.',
  },
];

// Short, direct answers: shown on the landing page and published as FAQPage data.
// Installing depends on the latest release, so that answer is filled in from it.
export function faq(release) {
  const install = {
    q: 'How do I install it?',
    a: `It isn't on PyPI yet, so pip installs it from GitHub: ${release.installCommand}. It needs Python 3.10+. You can also download the .whl from ${release.releaseUrl}.`,
  };
  return [QUESTIONS[0], install, ...QUESTIONS.slice(1)];
}
