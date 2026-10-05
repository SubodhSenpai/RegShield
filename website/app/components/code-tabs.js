'use client';

import { useState } from 'react';
import CodeBlock from './code-block';

// The integrations section: the text (children) and a picker on the left, the
// code for the picked integration on the right
export default function CodeTabs({ items, children }) {
  const [active, setActive] = useState(0);
  const item = items[active];
  return (
    <div className="feature">
      <div className="feature-text">
        {children}
        <div className="picker" role="tablist" aria-label="Integrations">
          {items.map((it, i) => (
            <button key={it.id} type="button" role="tab" aria-selected={i === active} onClick={() => setActive(i)}>
              {it.label}
              {i === active && <span className="picker-note">{it.note}</span>}
            </button>
          ))}
        </div>
      </div>
      <div className="feature-media" role="tabpanel">
        <CodeBlock code={item.code} lang={item.lang} />
      </div>
    </div>
  );
}
