'use client';

import { usePathname } from 'next/navigation';

const LINKS = [
  { href: '/docs', label: 'Docs' },
  { href: '/cookbook', label: 'Cookbook' },
  { href: '/#dashboard', label: 'Dashboard', wide: true },
];

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <nav className="nav-links" aria-label="Main">
      {LINKS.map(({ href, label, wide }) => {
        const current = href !== '/#dashboard' && (pathname === href || pathname.startsWith(`${href}/`));
        return (
          <a key={href} href={href} className={wide ? 'wide' : undefined} aria-current={current ? 'page' : undefined}>
            {label}
          </a>
        );
      })}
    </nav>
  );
}
