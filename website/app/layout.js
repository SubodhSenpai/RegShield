import './globals.css';

export const metadata = {
  title: 'RegressionShield | Deterministic Quality Gates for Agentic AI Reasoning',
  description: 'Catch silent reasoning failures, inverted prerequisite tool chains, loop thrashing, and policy evasion before they reach production. The developer-first evaluation suite built for autonomous agents.',
  keywords: ['AI agents evaluation', 'agentic reasoning', 'LLM evaluation', 'LangChain evaluation', 'smolagents', 'trace evaluation', 'regression testing', 'policy as code'],
  authors: [{ name: 'RegressionShield Team' }],
  openGraph: {
    title: 'RegressionShield | Deterministic Quality Gates for Agentic AI Reasoning',
    description: 'Catch silent reasoning failures, inverted prerequisite tool chains, and policy evasion before production.',
    type: 'website',
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        {/* Minimalist Top Announcement Bar */}
        <div style={{
          background: '#111114',
          borderBottom: '1px solid #1f1f23',
          padding: '8px 24px',
          fontSize: '12px',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '12px',
          color: '#a1a1aa',
          fontFamily: 'var(--font-mono)'
        }}>
          <span className="badge badge-info" style={{ padding: '2px 6px', fontSize: '10px' }}>SDK v0.2.0</span>
          <span>Deterministic execution trace evaluation now live with LangChain and smolagents adapters.</span>
          <a href="#integration" style={{ color: '#fafafa', textDecoration: 'underline', textUnderlineOffset: '3px' }}>
            Quickstart {'[->]'}
          </a>
        </div>

        {/* Main Navigation */}
        <header style={{
          position: 'sticky',
          top: 0,
          zIndex: 100,
          background: 'rgba(9, 9, 11, 0.85)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid var(--border)',
        }}>
          <div className="container" style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: '64px'
          }}>
            {/* Logo */}
            <a href="/" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fafafa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
              <span style={{ fontWeight: 700, fontSize: '16px', letterSpacing: '-0.02em', color: '#fafafa' }}>
                RegressionShield
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                color: '#71717a',
                background: '#18181b',
                padding: '2px 6px',
                borderRadius: '4px',
                border: '1px solid #27272a'
              }}>
                CORE
              </span>
            </a>

            {/* Links */}
            <nav style={{ display: 'flex', alignItems: 'center', gap: '28px', fontSize: '14px', fontWeight: 500, color: '#a1a1aa' }}>
              <a href="#problem" style={{ transition: 'color 0.15s' }}>Silent Failures</a>
              <a href="#simulator" style={{ transition: 'color 0.15s' }}>Trace Inspector</a>
              <a href="#benchmarks" style={{ transition: 'color 0.15s' }}>Benchmarks</a>
              <a href="#integration" style={{ transition: 'color 0.15s' }}>Integration</a>
              <a href="/docs" style={{ transition: 'color 0.15s', color: '#fafafa' }}>Documentation</a>
            </nav>

            {/* Action buttons */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '12px',
                fontFamily: 'var(--font-mono)',
                color: '#22c55e',
                background: '#052e16',
                border: '1px solid #166534',
                padding: '4px 8px',
                borderRadius: '4px'
              }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#22c55e', display: 'inline-block' }}></span>
                <span>GATE PASS</span>
              </div>

              <a
                href="https://github.com"
                target="_blank"
                rel="noreferrer"
                className="btn btn-secondary btn-sm"
                style={{ fontFamily: 'var(--font-mono)' }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
                  <path d="M9 18c-4.51 2-5-2-7-2" />
                </svg>
                GitHub
              </a>

              <a href="#integration" className="btn btn-primary btn-sm">
                Install SDK
              </a>
            </div>
          </div>
        </header>

        {/* Content */}
        <main style={{ flex: 1 }}>
          {children}
        </main>

        {/* Footer */}
        <footer style={{
          borderTop: '1px solid var(--border)',
          background: '#0a0a0c',
          padding: '64px 0 32px 0',
          marginTop: '80px',
        }}>
          <div className="container">
            <div style={{
              display: 'grid',
              gridTemplateColumns: '2fr 1fr 1fr 1fr',
              gap: '40px',
              marginBottom: '48px',
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fafafa" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  </svg>
                  <span style={{ fontWeight: 700, fontSize: '15px', color: '#fafafa' }}>RegressionShield</span>
                </div>
                <p style={{ fontSize: '13px', color: '#71717a', maxWidth: '320px', lineHeight: 1.6 }}>
                  Deterministic evaluation suite and CI/CD quality gate for agentic reasoning, ReAct traces, and multi-turn autonomous tool execution.
                </p>
                <div style={{ marginTop: '16px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#52525b' }}>
                  MIT License / Python 3.10+ / Zero Cloud Dependency Required
                </div>
              </div>

              <div>
                <h4 style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', textTransform: 'uppercase', color: '#fafafa', marginBottom: '14px', letterSpacing: '0.05em' }}>
                  Product
                </h4>
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px', color: '#a1a1aa' }}>
                  <li><a href="#simulator">Trace Inspector</a></li>
                  <li><a href="#problem">Silent Failure Modes</a></li>
                  <li><a href="#benchmarks">Competitor Matrix</a></li>
                  <li><a href="#integration">LangChain Callback</a></li>
                  <li><a href="#integration">smolagents Adapter</a></li>
                </ul>
              </div>

              <div>
                <h4 style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', textTransform: 'uppercase', color: '#fafafa', marginBottom: '14px', letterSpacing: '0.05em' }}>
                  Documentation
                </h4>
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px', color: '#a1a1aa' }}>
                  <li><a href="/docs">Getting Started</a></li>
                  <li><a href="/docs">Policy-as-Code Schema</a></li>
                  <li><a href="/docs">Core Scoring Metrics</a></li>
                  <li><a href="/docs">LLM-as-a-Judge Setup</a></li>
                  <li><a href="/docs">REST Ingestion API</a></li>
                </ul>
              </div>

              <div>
                <h4 style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', textTransform: 'uppercase', color: '#fafafa', marginBottom: '14px', letterSpacing: '0.05em' }}>
                  Ecosystem
                </h4>
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px', color: '#a1a1aa' }}>
                  <li><a href="https://pypi.org" target="_blank" rel="noreferrer">PyPI: regression-shield</a></li>
                  <li><a href="https://github.com" target="_blank" rel="noreferrer">GitHub Repository</a></li>
                  <li><a href="/docs">CI/CD GitHub Action</a></li>
                  <li><a href="#integration">CLI Reference</a></li>
                </ul>
              </div>
            </div>

            <div style={{
              borderTop: '1px solid #1a1a1e',
              paddingTop: '24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '12px',
              color: '#52525b',
              fontFamily: 'var(--font-mono)'
            }}>
              <div>[SYSTEM STATUS: ALL QUALITY GATES NOMINAL]</div>
              <div>DESIGNED FOR AGENTIC RELIABILITY ENGINEERING</div>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
