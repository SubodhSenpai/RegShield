import { DOCS } from '../../lib/docs';
import { NAME, REPO, SITE_URL } from '../../lib/site';

export default function DocPage({ doc }) {
  const article = {
    '@context': 'https://schema.org',
    '@type': 'TechArticle',
    headline: doc.title,
    description: doc.description,
    url: `${SITE_URL}${doc.href}`,
    isPartOf: { '@type': 'WebSite', name: NAME, url: SITE_URL },
  };
  return (
    <div className="wrap docs">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(article) }} />
      <aside className="sidebar" aria-label="Documentation">
        <p className="sidebar-title">Docs</p>
        <ul>
          {DOCS.map((d) => (
            <li key={d.slug}>
              <a href={d.href} aria-current={d.slug === doc.slug ? 'page' : undefined}>{d.title}</a>
              {d.slug === doc.slug && doc.headings.length > 0 && (
                <ul className="toc">
                  {doc.headings.map((h) => (
                    <li key={h.id} className={`d${h.depth}`}><a href={`#${h.id}`}>{h.text}</a></li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
        <div className="sidebar-foot">
          <a href={`${REPO}/tree/main/examples`} target="_blank" rel="noreferrer">Runnable examples ↗</a>
        </div>
      </aside>
      <div className="prose">
        <div dangerouslySetInnerHTML={{ __html: doc.html }} />
        <p className="doc-edit">
          This page is <a href={`${REPO}/blob/main/docs/${doc.file}`} target="_blank" rel="noreferrer">docs/{doc.file}</a> in
          the repository. Corrections welcome.
        </p>
      </div>
      {/* On wide screens the page's contents move out of the sidebar into their own column */}
      {doc.headings.length > 0 && (
        <nav className="page-toc" aria-label="On this page">
          <p className="sidebar-title">On this page</p>
          <ul className="toc">
            {doc.headings.map((h) => (
              <li key={h.id} className={`d${h.depth}`}><a href={`#${h.id}`}>{h.text}</a></li>
            ))}
          </ul>
        </nav>
      )}
    </div>
  );
}
