// The latest GitHub release: the version the site shows and the wheel its install
// commands point at. RegShield isn't on PyPI yet, so pip installs the wheel attached
// to the release. The site asks GitHub when it's built and again at most once an
// hour, so a new release shows up without a redeploy.

import fs from 'node:fs';
import path from 'node:path';
import { REPO } from './site';

const LATEST = 'https://api.github.com/repos/SubodhSenpai/RegShield/releases/latest';

function wheelUrl(version) {
  return `${REPO}/releases/download/v${version}/regression_shield-${version}-py3-none-any.whl`;
}

function release(version, releaseUrl, wheel) {
  return { version, releaseUrl, wheelUrl: wheel, installCommand: `pip install ${wheel}` };
}

// The version in the repository (regression_shield/__init__.py), for when GitHub
// can't be reached, such as a build without network access
function repositoryRelease() {
  const source = fs.readFileSync(path.join(process.cwd(), '..', 'regression_shield', '__init__.py'), 'utf-8');
  const version = source.match(/^__version__\s*=\s*["']([^"']+)["']/m)[1];
  return release(version, `${REPO}/releases/tag/v${version}`, wheelUrl(version));
}

export async function latestRelease() {
  try {
    const response = await fetch(LATEST, {
      headers: {
        Accept: 'application/vnd.github+json',
        // Optional: a token raises GitHub's rate limit, which build machines share
        ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
      },
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(8000),
    });
    if (response.ok) {
      const latest = await response.json();
      const version = latest.tag_name.replace(/^v/, '');
      const wheel = latest.assets.find((asset) => asset.name.endsWith('-py3-none-any.whl'));
      return release(version, latest.html_url, wheel ? wheel.browser_download_url : wheelUrl(version));
    }
  } catch {
    // GitHub unreachable: use the repository's version below
  }
  return repositoryRelease();
}

// Install links in the docs name the release they were written for. On the site
// they always point at the latest release.
export function withRelease(markdown, { version }) {
  return markdown
    .replace(/releases\/download\/v[\w.]+\/regression_shield-[\w.]+-py3-none-any\.whl/g,
      `releases/download/v${version}/regression_shield-${version}-py3-none-any.whl`)
    .replace(/(github\.com\/SubodhSenpai\/RegShield(?:\.git)?)@v[\w.]+/g, `$1@v${version}`);
}
