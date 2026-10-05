// The link preview image (Open Graph and Twitter): the headline and a real failure line.

import { ImageResponse } from 'next/og';

export const alt = 'RegShield: regression tests for AI agents';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: 72, background: '#11100e', color: '#eee8de' }}>
        <div style={{ display: 'flex', alignItems: 'center', fontSize: 30 }}>
          regshield
          <div style={{ width: 14, height: 30, marginLeft: 6, background: '#ebb561' }} />
        </div>
        <div style={{ display: 'flex', fontSize: 84, lineHeight: 1.05, letterSpacing: '-0.03em', maxWidth: 820 }}>
          Regression tests for AI agents
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', fontSize: 26, color: '#b8b0a4', border: '1px solid #3b3733', borderRadius: 14, padding: '22px 28px', background: '#0b0a09' }}>
          <div style={{ display: 'flex' }}>
            <span style={{ color: '#ef7e67', marginRight: 18 }}>FAIL</span>refund_approval
          </div>
          <div style={{ display: 'flex', marginTop: 8 }}>
            Step 3:&nbsp;<span style={{ color: '#ebb561' }}>&apos;issue_refund&apos;</span>&nbsp;ran after its approval was denied
          </div>
        </div>
      </div>
    ),
    size,
  );
}
