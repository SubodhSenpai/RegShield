// Site-wide facts used by metadata, structured data, the sitemap and llms.txt.

// Set SITE_URL when deploying (e.g. https://regshield.example.com). On Vercel the
// production domain is picked up automatically.
export const SITE_URL = (
  process.env.SITE_URL ||
  (process.env.VERCEL_PROJECT_PRODUCTION_URL && `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`) ||
  'http://localhost:3000'
).replace(/\/$/, '');

export const NAME = 'RegShield';
export const VERSION = '0.4.0';
export const REPO = 'https://github.com/SubodhSenpai/RegShield';
export const PYPI = 'https://pypi.org/project/regression-shield/';
export const TITLE = 'RegShield: regression tests for AI agents';
export const DESCRIPTION =
  'Open-source Python library that tests AI agents by their tool calls. Checks order, arguments, handoffs and approvals, offline, in pytest or CI.';

// Short, direct answers: shown on the landing page and published as FAQPage data
export const FAQ = [
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
    a: 'LangChain and LangGraph through one callback handler, Hugging Face smolagents (including CodeAgent), any Python agent loop through TraceRecorder, and any language through a local REST API.',
  },
  {
    q: 'Does it send my data anywhere?',
    a: 'No. The checks and the dashboard run on your machine, and the dashboard listens on 127.0.0.1 only. Only the optional LLM judge makes a network call, to the endpoint and key you configure.',
  },
  {
    q: 'How do I run it in CI?',
    a: 'Call raise_for_failures() in a pytest test, or run regshield eval scenarios.json. The command exits with code 1 when a scenario fails, so the pipeline stops.',
  },
];
