'use client';

import Image from 'next/image';
import { useState } from 'react';

const VIEWS = [
  { id: 'inspector', label: 'Trace inspector', src: '/docs-images/dashboard.png', alt: 'RegShield dashboard showing a failed scenario: its five scores and the violations it broke' },
  { id: 'matrix', label: 'Baseline vs. regression', src: '/docs-images/dashboard-matrix.png', alt: 'RegShield dashboard table comparing each passing trace with its known-bad version, all marked caught' },
];

// The dashboard section: a screenshot on the left, the text (children) and a
// view picker on the right
export default function Screenshots({ children }) {
  const [active, setActive] = useState(0);
  const view = VIEWS[active];
  return (
    <div className="feature media-first">
      <div className="feature-text">
        {children}
        <div className="picker" role="tablist" aria-label="Dashboard views">
          {VIEWS.map((v, i) => (
            <button key={v.id} type="button" role="tab" aria-selected={i === active} onClick={() => setActive(i)}>
              {v.label}
            </button>
          ))}
        </div>
      </div>
      <div className="feature-media window">
        <div className="window-bar">
          <span className="url"><b>localhost:8000</b></span>
        </div>
        <Image src={view.src} alt={view.alt} width={1440} height={910} sizes="(max-width: 900px) 100vw, 45vw" />
      </div>
    </div>
  );
}
