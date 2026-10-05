export const metadata = { title: 'Page not found' };

export default function NotFound() {
  return (
    <section className="section not-found">
      <div className="wrap">
        <p className="not-found-code">404</p>
        <h1>This page isn&apos;t here</h1>
        <p>It may have moved when the docs changed.</p>
        <p className="not-found-links">
          <a href="/" className="arrow-link">Home</a>
          <a href="/docs" className="arrow-link">Docs</a>
          <a href="/cookbook" className="arrow-link">Cookbook</a>
        </p>
      </div>
    </section>
  );
}
