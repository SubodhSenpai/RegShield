'use client';

import { useState } from 'react';

// A shell command you copy with one click. pip installs packages from the
// terminal, so the site copies the command rather than downloading anything.
export default function Install({ command = 'pip install regression-shield' }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard blocked (e.g. an insecure context): the command stays visible to copy by hand
    }
  }

  return (
    <button type="button" className={`install${copied ? ' copied' : ''}`} onClick={copy} aria-label={`Copy command: ${command}`}>
      <span className="prompt">$</span>
      <span>{command}</span>
      <span className="hint" aria-live="polite">{copied ? 'copied' : 'copy'}</span>
    </button>
  );
}
