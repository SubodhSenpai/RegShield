# RegShield website

The site at the root of this folder: a landing page, the docs and the cookbook. Next.js, no other framework.

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # static pages, checked for errors
```

The docs and cookbook pages are the repository's `../docs/*.md` files, rendered at build time (`lib/docs.js`), so edit the Markdown there, not here. When deploying from this folder (for example Vercel with the root directory set to `website`), keep source files outside the root directory available to the build.

Set `SITE_URL` (for example `https://regshield.example.com`) when you deploy. Canonical links, the sitemap, `robots.txt`, `llms.txt` and the link preview image use it; on Vercel the production domain is picked up automatically. Site-wide text (description, FAQ) lives in `lib/site.js`.

The landing page's terminal shows real `regshield` output; if the CLI's output changes, update `SESSIONS` and `LEDGER` in `app/page.js` to match. Screenshots live in `../docs/images/` (served at `/docs-images/`) and come from `regshield demo` followed by `regshield serve`.
