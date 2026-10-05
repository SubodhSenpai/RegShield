import { IBM_Plex_Mono, IBM_Plex_Sans } from 'next/font/google';
import CopyButtons from './components/copy-buttons';
import Landscape from './components/landscape';
import NavLinks from './components/nav-links';
import { DESCRIPTION, NAME, PYPI, REPO, SITE_URL, TITLE, VERSION } from '../lib/site';
import './globals.css';

const sans = IBM_Plex_Sans({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--font-sans', display: 'swap' });
const mono = IBM_Plex_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--font-mono', display: 'swap' });

export const metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: TITLE, template: `%s · ${NAME}` },
  description: DESCRIPTION,
  applicationName: NAME,
  authors: [{ name: 'Subodh', url: 'https://github.com/SubodhSenpai' }],
  keywords: [
    'AI agent testing', 'agent evaluation', 'regression testing', 'LLM agents', 'tool calling',
    'LangChain', 'LangGraph', 'smolagents', 'pytest', 'CI', 'human in the loop', 'multi-agent',
  ],
  alternates: { canonical: '/' },
  openGraph: { type: 'website', siteName: NAME, title: TITLE, description: DESCRIPTION, url: '/' },
  twitter: { card: 'summary_large_image', title: TITLE, description: DESCRIPTION },
};

export const viewport = { themeColor: '#11100e' };

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <Landscape />
        <header className="nav">
          <div className="wrap">
            <a href="/" className="wordmark" aria-label="RegShield home">
              regshield<span className="caret" aria-hidden="true" />
            </a>
            <NavLinks />
            <div className="nav-right">
              <span className="version">v{VERSION}</span>
              <a href={REPO} target="_blank" rel="noreferrer">GitHub</a>
            </div>
          </div>
        </header>
        <main>{children}</main>
        <footer className="footer">
          <div className="wrap">
            <p className="credit">Co-powered by <strong>Konika Systems Private Limited</strong></p>
            <nav aria-label="Footer">
              <a href="/docs">Docs</a>
              <a href="/cookbook">Cookbook</a>
              <a href={REPO} target="_blank" rel="noreferrer">GitHub</a>
              <a href={PYPI} target="_blank" rel="noreferrer">PyPI</a>
            </nav>
          </div>
        </footer>
        <CopyButtons />
      </body>
    </html>
  );
}
