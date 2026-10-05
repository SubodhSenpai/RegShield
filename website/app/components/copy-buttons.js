'use client';

import { useEffect } from 'react';

// Code blocks in the rendered docs are plain HTML; one listener makes their
// "copy" buttons work.
export default function CopyButtons() {
  useEffect(() => {
    async function onClick(event) {
      const button = event.target.closest('[data-copy]');
      if (!button) return;
      const code = button.closest('.code')?.querySelector('code')?.innerText ?? '';
      try {
        await navigator.clipboard.writeText(code);
        button.textContent = 'copied';
        setTimeout(() => { button.textContent = 'copy'; }, 1400);
      } catch {
        // Clipboard unavailable; the code can still be selected by hand
      }
    }
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);
  return null;
}
