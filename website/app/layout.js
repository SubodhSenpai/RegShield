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
          background: 'rgba(255, 255, 255, 0.88)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          borderBottom: '1px solid var(--border)',
        }}>
          <div className="wrap" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            {/* Logo */}
            <a href="/" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)' }}>RegressionShield</span>
            </a>

            {/* Links */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '32px', fontSize: '13px', color: 'var(--text3)' }}>
              <a href="#how-it-works" style={{ transition: 'color 0.15s' }}>How it works</a>
              <a href="#compare" style={{ transition: 'color 0.15s' }}>Compare</a>
              <a href="#integrate" style={{ transition: 'color 0.15s' }}>Integrate</a>
              <a href="/docs" style={{ color: 'var(--text)', fontWeight: 500 }}>Docs</a>
            </div>

            {/* Right */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontFamily: 'var(--mono)',
                fontSize: '11px',
                color: 'var(--text2)',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                padding: '4px 10px',
                borderRadius: '9999px',
                boxShadow: 'var(--shadow-xs)',
              }}>
                <span className="dot"></span>
                v0.3.0 stable
              </div>
              <a href="#integrate" className="btn btn-primary" style={{ padding: '7px 16px', fontSize: '13px' }}>
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
          borderTop: '1px solid var(--border)',
          padding: '48px 0',
          marginTop: '120px',
          background: 'var(--bg)',
        }}>
          <div className="wrap" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '13px', color: 'var(--text2)', fontWeight: 600 }}>RegressionShield</span>
              <span style={{ fontSize: '13px', color: 'var(--text3)' }}>— MIT License</span>
            </div>

            <div style={{ display: 'flex', gap: '24px', fontSize: '13px', color: 'var(--text3)' }}>
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
