import { notFound } from 'next/navigation';
import DocPage from '../../components/doc-page';
import { DOCS, docMetadata, loadDoc } from '../../../lib/docs';

// /docs shows Getting started and /cookbook the cookbook; the other guides live here
const PAGES = DOCS.filter((d) => d.href === `/docs/${d.slug}`);

export const dynamicParams = false;

export function generateStaticParams() {
  return PAGES.map((d) => ({ slug: d.slug }));
}

export async function generateMetadata({ params }) {
  const { slug } = await params;
  const doc = loadDoc(slug);
  return doc ? docMetadata(doc) : {};
}

export default async function Guide({ params }) {
  const { slug } = await params;
  if (!PAGES.some((d) => d.slug === slug)) notFound();
  return <DocPage doc={loadDoc(slug)} />;
}
