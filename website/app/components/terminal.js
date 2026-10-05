'use client';

import { useRef, useState } from 'react';
import { Highlight } from '../../lib/highlight';

// Replays real RegShield sessions: the command types out, then the output
// prints line by line. The animation is CSS only, so it restarts whenever the
// session changes and is skipped for people who prefer reduced motion.
export default function Terminal({ sessions, cwd }) {
  const [active, setActive] = useState(0);
  const [runs, setRuns] = useState(0);
  const body = useRef(null);
  const session = sessions[active];
  const lines = session.output.split('\n');
  const typing = 350 + session.command.length * 28;

  function show(index) {
    setActive(index);
    setRuns((n) => n + 1);
  }

  // On short screens the window is smaller than the output, so it scrolls to
  // keep the newest line in view, like a real terminal
  function follow(event) {
    const el = body.current;
    if (!el || !event.target.classList.contains('term-line')) return;
    const pad = parseFloat(getComputedStyle(el).paddingBottom);
    const below = event.target.getBoundingClientRect().bottom + pad - el.getBoundingClientRect().bottom;
    if (below > 0) el.scrollTop += below;
  }

  return (
    <div className="term">
      <div className="term-bar" role="tablist" aria-label="Terminal sessions">
        {sessions.map((s, i) => (
          <button key={s.id} type="button" role="tab" aria-selected={i === active} className="term-tab" onClick={() => show(i)}>
            {s.label}
          </button>
        ))}
        <span className="term-cwd">{cwd}</span>
      </div>
      <pre className="term-body" key={`${session.id}-${runs}`} ref={body} role="tabpanel" tabIndex={0} onAnimationEnd={follow}>
        <span className="hl-p">$ </span>
        <span className="term-typed" style={{ '--chars': session.command.length }}>{session.command}</span>
        {'\n'}
        {lines.map((line, i) => (
          <span key={i} className="term-line" style={{ animationDelay: `${typing + i * 55}ms` }}>
            <Highlight code={line} lang="output" />
            {'\n'}
          </span>
        ))}
        <span className="term-line" style={{ animationDelay: `${typing + lines.length * 55}ms` }}>
          <span className="hl-p">$ </span>
          <span className="term-cursor" />
        </span>
      </pre>
    </div>
  );
}
