import './globals.css';

export const metadata = {
  title: 'RegressionShield — Quality Gates for AI Agents',
  description: 'Deterministic evaluation suite that catches silent reasoning failures in autonomous AI agents before they reach production.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {/* Nav */}
        <nav style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 100,
          height: '56px',
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(10,10,10,0.8)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          borderBottom: '1px solid #1a1a1a',
        }}>
          <div className="wrap" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            {/* Logo */}
            <a href="/" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f5f5f5" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              <span style={{ fontSize: '14px', fontWeight: 600, letterSpacing: '-0.01em' }}>RegressionShield</span>
            </a>

            {/* Links */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '32px', fontSize: '13px', color: '#888' }}>
              <a href="#how-it-works" style={{ transition: 'color 0.15s' }}>How it works</a>
              <a href="#compare" style={{ transition: 'color 0.15s' }}>Compare</a>
              <a href="#integrate" style={{ transition: 'color 0.15s' }}>Integrate</a>
              <a href="/docs" style={{ color: '#f5f5f5' }}>Docs</a>
            </div>

            {/* Right */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--mono)', fontSize: '11px', color: '#22c55e' }}>
                <span className="dot"></span>
                v0.2.0 stable
              </div>
              <a href="#integrate" className="btn btn-white" style={{ padding: '7px 16px', fontSize: '13px' }}>
                Get started
              </a>
            </div>
          </div>
        </nav>

        {/* Page content */}
        <main style={{ paddingTop: '56px' }}>
          {children}
        </main>

        {/* Footer */}
        <footer style={{
          borderTop: '1px solid #1a1a1a',
          padding: '48px 0',
          marginTop: '120px',
        }}>
          <div className="wrap" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#555" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              <span style={{ fontSize: '13px', color: '#555', fontWeight: 500 }}>RegressionShield</span>
              <span style={{ fontSize: '13px', color: '#333' }}>— MIT License</span>
            </div>

            <div style={{ display: 'flex', gap: '24px', fontSize: '13px', color: '#555' }}>
              <a href="/docs">Documentation</a>
              <a href="https://github.com" target="_blank" rel="noreferrer">GitHub</a>
              <a href="https://pypi.org" target="_blank" rel="noreferrer">PyPI</a>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
