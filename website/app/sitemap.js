import { DOCS } from '../lib/docs';
import { SITE_URL } from '../lib/site';

export default function sitemap() {
  return [
    { url: `${SITE_URL}/`, changeFrequency: 'monthly', priority: 1 },
    ...DOCS.map((doc) => ({ url: `${SITE_URL}${doc.href}`, changeFrequency: 'monthly', priority: 0.8 })),
  ];
}
