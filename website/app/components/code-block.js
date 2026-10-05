'use client';

import { useState } from 'react';
import { Highlight, languageOf } from '../../lib/highlight';

export default function CodeBlock({ code, lang }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard unavailable; the code can still be selected by hand
    }
  }

  const output = languageOf(lang) === 'output';
  return (
    <div className={`code${output ? ' is-output' : ''}`}>
      <div className="code-bar">
        <span>{output ? 'output' : lang}</span>
        <button type="button" className="copy" onClick={copy}>{copied ? 'copied' : 'copy'}</button>
      </div>
      <pre><code><Highlight code={code} lang={lang} /></code></pre>
    </div>
  );
}
