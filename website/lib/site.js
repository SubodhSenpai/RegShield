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
  'Open-source Python library that tests AI agents by their tool calls. Checks order, arguments, handoffs and approvals, offline, in pytest or CI.';

const QUESTIONS = [
  {
    q: 'What is RegShield?',
    a: 'RegShield is an open-source Python library (MIT) for regression testing AI agents. It checks an agent\'s execution trace, meaning which tools ran, in what order, with which arguments, and who approved them, against rules you write once.',
  },
  {
    q: 'How is it different from LLM evals?',
    a: 'Most evals grade the final answer. RegShield checks the actions behind it, with deterministic rules that need no LLM and no API key. An optional LLM judge covers what rules cannot see, such as a wrong amount in the answer.',
  },
  {
    q: 'Which agent frameworks does it work with?',
    a: 'LangChain and LangGraph through one callback handler, Hugging Face smolagents (including CodeAgent), your own loop on the OpenAI, Anthropic or Gemini SDK with no code changes, any Python agent loop through TraceRecorder, and any language through a local REST API.',
  },
  {
    q: 'Does it send my data anywhere?',
    a: 'No. The checks and the dashboard run on your machine, and the dashboard listens on 127.0.0.1 only. Network calls happen only for what you turn on: the LLM judge calls the endpoint you configure, exported runs go to the destinations you name, and regshield pricing refresh downloads public model prices.',
  },
  {
    q: 'How do I run it in CI?',
    a: 'Call raise_for_failures() in a pytest test, or run regshield eval scenarios.json. The command exits with code 1 when a scenario fails, so the pipeline stops.',
  },
];

// Short, direct answers: shown on the landing page and published as FAQPage data.
// Installing depends on the latest release, so that answer is filled in from it.
export function faq(release) {
  const install = {
    q: 'How do I install it?',
    a: `RegShield isn't on PyPI yet. Each GitHub release carries the built package, and pip installs it straight from GitHub: ${release.installCommand}. It needs Python 3.10 or newer. You can also download the .whl from ${release.releaseUrl} and pip install the file.`,
  };
  return [QUESTIONS[0], install, ...QUESTIONS.slice(1)];
}
