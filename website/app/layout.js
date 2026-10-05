import { IBM_Plex_Mono, IBM_Plex_Sans } from 'next/font/google';
import CopyButtons from './components/copy-buttons';
import Landscape from './components/landscape';
import NavLinks from './components/nav-links';
import { latestRelease } from '../lib/release';
import { DESCRIPTION, NAME, RELEASES, REPO, SITE_URL, TITLE } from '../lib/site';
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

// Every page shows the latest release; GitHub is asked again at most once an hour
export const revalidate = 3600;

export default async function RootLayout({ children }) {
  const release = await latestRelease();
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
              <a href={release.releaseUrl} className="version" target="_blank" rel="noreferrer" title="Latest release">v{release.version}</a>
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
              <a href={RELEASES} target="_blank" rel="noreferrer">Releases</a>
            </nav>
          </div>
        </footer>
        <CopyButtons />
      </body>
    </html>
  );
}
