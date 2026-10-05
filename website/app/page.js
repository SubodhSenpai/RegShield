import CodeTabs from './components/code-tabs';
import Install from './components/install';
import Screenshots from './components/screenshots';
import Terminal from './components/terminal';
import { loadDoc } from '../lib/docs';
import { Highlight } from '../lib/highlight';
import { DESCRIPTION, FAQ, NAME, PYPI, REPO, SITE_URL, VERSION } from '../lib/site';

const RECIPE_COUNT = loadDoc('cookbook').headings.filter((h) => h.depth === 3).length;

// Real output, copied from runs of RegShield 0.4.0 on a small support-agent suite
const SESSIONS = [
  {
    id: 'eval',
    label: 'regshield eval',
    command: 'regshield eval scenarios.json',
    output: `Evaluating 4 scenario(s) from scenarios.json

PASS  deploy_gate  (composite 1.00)
      patterns: Policy PASS
FAIL  refund_approval  (composite 1.00)
      patterns: Human Approval FAIL
      - Human Approval: Step 3: 'issue_refund' ran after its approval was denied
PASS  support_router  (composite 1.00)
      patterns: Routing PASS
FAIL  wire_transfer  (composite 0.65)
      - Call ordering 0.00 < 1.00: 'verify_identity' never ran ('verify_identity' must come before 'send_wire')
      - Reasoning faithfulness 0.00 < 0.85: Final response claims success right after an error

2/4 scenario(s) passed. Routing accuracy: 1/1 (100%).
Report saved to /home/you/support-agent/reports/latest_report.json`,
  },
  {
    id: 'pytest',
    label: 'pytest',
    command: 'pytest -q --tb=short',
    output: `.F                                                                       [100%]
================================== FAILURES ===================================
____________________________ test_refund_approval _____________________________
E   regression_shield.models.EvaluationFailed: refund_approval failed:
E     - Human Approval: Step 3: 'issue_refund' ran after its approval was denied
=========================== short test summary info ===========================
FAILED test_support_agent.py::test_refund_approval - regression_shield.models...
1 failed, 1 passed in 0.45s`,
  },
  {
    id: 'serve',
    label: 'regshield serve',
    command: 'regshield serve',
    output: `RegShield dashboard: http://localhost:8000
Reports: /home/you/support-agent/reports/latest_report.json
LLM judge: off
Press Ctrl+C to stop.`,
  },
];

// Exactly what RegShield prints; each row links to the recipe that produces it
const LEDGER = [
  ['order', "'deploy' (step 1) ran before its prerequisite 'run_tests' (step 2)", 'run-the-tests-before-a-deploy', 'expected_order'],
  ['arguments', "convert.amount was '1', expected 431.2", 'check-the-arguments', 'expected_arguments'],
  ['approval', "Step 2: 'issue_refund' ran after its approval was denied", 'ask-a-person-before-refunding', 'requires_approval'],
  ['answer', 'Final response claims success right after an error', 'catch-done-after-a-failed-call', 'always on'],
  ['policy', "Step 3: called forbidden tool 'delete_account'", 'never-call-a-dangerous-tool-and-refund-once-at-most', 'forbidden_tools'],
  ['agents', "Step 2: agent 'triage' called 'issue_refund', which isn't in its allowed tools", 'keep-each-agent-to-its-own-tools', 'agent_tools'],
  ['graph', "Step 4: 'draft' -> 'publish' is not an allowed transition", 'allow-only-certain-graph-transitions', 'allowed_transitions'],
  ['loops', '3 steps for an optimal 1, 2 repeated call(s)', 'stop-an-agent-that-loops', 'optimal_step_count'],
];

const INTEGRATIONS = [
  {
    id: 'langgraph',
    label: 'LangGraph',
    note: 'One callback records nodes, sub-agents, handoffs and approvals.',
    lang: 'python',
    code: `from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})  # app = graph.compile()

report = evaluate_trace({
    "scenario_id": "content_pipeline",
    "allowed_transitions": {"writer": ["reviewer"], "reviewer": ["writer", "publish"]},
    "max_node_visits": {"reviewer": 3},
}, handler)
report.raise_for_failures()`,
  },
  {
    id: 'langchain',
    label: 'LangChain',
    note: 'The same callback works for create_agent agents and chains.',
    lang: 'python',
    code: `from langchain.agents import create_agent
from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

agent = create_agent(model, tools=[lookup_order, issue_refund])
handler = RegressionShieldCallbackHandler()
agent.invoke({"messages": [{"role": "user", "content": "Refund order A-1042"}]},
             config={"callbacks": [handler]})

report = evaluate_trace({
    "scenario_id": "refund",
    "expected_order": ["lookup_order", "issue_refund"],
    "max_tool_calls": {"issue_refund": 1},
}, handler)`,
  },
  {
    id: 'smolagents',
    label: 'smolagents',
    note: 'Instrument before the run. CodeAgent works too.',
    lang: 'python',
    code: `from smolagents import CodeAgent
from regression_shield import evaluate_trace, instrument_smolagents

agent = CodeAgent(tools=[get_stock_price, convert_currency], model=model)
recorder = instrument_smolagents(agent)
agent.run("What is Apple's share price in euros?")

report = evaluate_trace({
    "scenario_id": "price_in_euros",
    "expected_order": ["get_stock_price", "convert_currency"],
}, recorder)`,
  },
  {
    id: 'loop',
    label: 'Your own loop',
    note: 'Wrap your tools and every call is recorded.',
    lang: 'python',
    code: `from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()
lookup_order = recorder.wrap(lookup_order)
issue_refund = recorder.wrap(issue_refund)

answer = run_my_agent("Refund order A-1042", tools=[lookup_order, issue_refund])
recorder.final_answer(answer)

report = evaluate_trace(scenario, recorder)`,
  },
  {
    id: 'pytest',
    label: 'pytest',
    note: 'Fails the test and lists every reason.',
    lang: 'python',
    code: `from regression_shield import evaluate_trace

def test_refund_approval():
    trace = run_support_agent("Refund order A-1042")
    evaluate_trace(REFUND_SCENARIO, trace).raise_for_failures()`,
  },
  {
    id: 'ci',
    label: 'GitHub Actions',
    note: 'Exits with 1 when a scenario fails.',
    lang: 'yaml',
    code: `on: [pull_request]
jobs:
  agents:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install regression-shield
      - run: regshield eval scenarios.json`,
  },
  {
    id: 'rest',
    label: 'REST',
    note: 'Any language: post the trace to regshield serve.',
    lang: 'bash',
    code: `curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{"scenario": {"scenario_id": "deploy_gate", "expected_order": ["run_tests", "deploy"]},
       "trace": [{"action": {"name": "deploy", "args": {}}, "observation": "DEPLOYED"}]}'`,
  },
];

const RECIPES = [
  ['Run the tests before a deploy', 'run-the-tests-before-a-deploy'],
  ['Ask a person before refunding', 'ask-a-person-before-refunding'],
  ['Catch "done!" after a failed call', 'catch-done-after-a-failed-call'],
  ['Keep each agent to its own tools', 'keep-each-agent-to-its-own-tools'],
  ['Allow only certain graph transitions', 'allow-only-certain-graph-transitions'],
  ['Judge answers with a local model', 'judge-answers-with-a-local-model'],
  ['Gate pull requests', 'gate-pull-requests'],
  ['Set a stricter threshold', 'set-a-stricter-threshold'],
];

// Structured data for search engines and answer engines
const JSON_LD = [
  {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: NAME,
    alternateName: 'regression-shield',
    description: DESCRIPTION,
    url: SITE_URL,
    applicationCategory: 'DeveloperApplication',
    operatingSystem: 'Windows, macOS, Linux',
    softwareVersion: VERSION,
    license: 'https://opensource.org/licenses/MIT',
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    downloadUrl: PYPI,
    sameAs: [REPO, PYPI],
  },
  {
    '@context': 'https://schema.org',
    '@type': 'SoftwareSourceCode',
    name: NAME,
    codeRepository: REPO,
    programmingLanguage: 'Python',
    runtimePlatform: 'Python 3.10+',
    license: 'https://opensource.org/licenses/MIT',
  },
  {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: FAQ.map(({ q, a }) => ({ '@type': 'Question', name: q, acceptedAnswer: { '@type': 'Answer', text: a } })),
  },
];

export default function Home() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />

      <section className="hero">
        <div className="hero-inner wrap">
          <h1>Regression tests for AI agents</h1>
          <p className="hero-sub">Check every tool call your agent makes against rules you write. Runs offline, in pytest or CI.</p>
          <div className="hero-actions">
            <Install />
            <a href="/docs" className="arrow-link">Get started →</a>
          </div>
          <Terminal sessions={SESSIONS} cwd="~/support-agent" />
        </div>
      </section>

      <section className="section" id="checks" aria-labelledby="checks-title">
        <div className="wrap">
          <header className="section-head">
            <h2 id="checks-title">Failures you can read</h2>
          </header>
          <ol className="ledger">
            {LEDGER.map(([check, message, recipe, field]) => (
              <li key={check}>
                <a href={`/cookbook#${recipe}`}>
                  <span className="check">{check}</span>
                  <span className="msg"><Highlight code={message} lang="output" /></span>
                  <span className="field">{field}</span>
                </a>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section" id="dashboard" aria-labelledby="dashboard-title">
        <div className="wrap">
          <Screenshots>
            <h2 id="dashboard-title">A dashboard on localhost</h2>
            <p>Every trace step by step, with known-bad runs next to good ones. No account, nothing uploaded.</p>
            <Install command="regshield serve" />
          </Screenshots>
        </div>
      </section>

      <section className="section" id="integrations" aria-labelledby="integrations-title">
        <div className="wrap">
          <CodeTabs items={INTEGRATIONS}>
            <h2 id="integrations-title">Works with your agent</h2>
          </CodeTabs>
        </div>
      </section>

      <section className="section" id="cookbook" aria-labelledby="cookbook-title">
        <div className="wrap">
          <header className="section-head row">
            <h2 id="cookbook-title">Cookbook</h2>
            <a href="/cookbook" className="arrow-link">All {RECIPE_COUNT} recipes →</a>
          </header>
          <ul className="recipes">
            {RECIPES.map(([title, slug]) => (
              <li key={slug}><a href={`/cookbook#${slug}`}>{title}</a></li>
            ))}
          </ul>
        </div>
      </section>

      <section className="section" id="faq" aria-labelledby="faq-title">
        <div className="wrap faq">
          <h2 id="faq-title">Questions</h2>
          <div>
            {FAQ.map(({ q, a }) => (
              <details key={q}>
                <summary>{q}</summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
