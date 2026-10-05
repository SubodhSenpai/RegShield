// A small syntax highlighter for the languages on this site. It splits code into
// [text, kind] tokens; kind is '' for plain text. Output blocks (RegShield's own
// output, shell sessions) get their own rules: PASS/FAIL, quoted names, prompts.

const PYTHON_KEYWORDS = new Set(
  'False None True and as async await class def elif else except for from if import in is lambda not or pass raise return try while with yield'.split(' '),
);

const STRING = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/y;
const NUMBER = /\b\d+(?:\.\d+)?\b/y;

const RULES = {
  python: [
    ['c', /#[^\n]*/y],
    ['s', /[rbfu]{0,2}(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')/y],
    ['d', /@[\w.]+/y],
    ['n', NUMBER],
    ['w', /[A-Za-z_]\w*/y],
  ],
  bash: [
    ['c', /(?<=^|\s)#[^\n]*/y],
    ['p', /^\$ /my],
    ['s', STRING],
    ['d', /--?[\w-]+/y],
    ['w', /[A-Za-z_][\w-]*/y],
  ],
  json: [
    ['k', /"(?:[^"\\\n]|\\.)*"(?=\s*:)/y],
    ['s', STRING],
    ['n', /-?\b\d+(?:\.\d+)?\b|\b(?:true|false|null)\b/y],
  ],
  yaml: [
    ['c', /(?<=^|\s)#[^\n]*/y],
    ['k', /(?<=^[ \t-]*)[\w./-]+(?=:)/my],
    ['s', STRING],
    ['n', NUMBER],
  ],
  output: [
    ['p', /^\$ [^\n]*/my],
    ['fail', /\b(?:FAILED|FAIL)\b|\b\d+ failed\b|^E(?= )/my],
    ['pass', /\b(?:PASSED|PASS)\b|\b\d+ passed\b/y],
    ['miss', /\bMISS\b/y],
    // Quoted tool and agent names; a quote inside a word ("isn't") doesn't start one
    ['q', /(?<!\w)'[^'\n]*'/y],
    ['n', /\b\d+\.\d+\b/y],
  ],
};

const ALIASES = { py: 'python', sh: 'bash', shell: 'bash', console: 'output', text: 'output', yml: 'yaml' };

export function languageOf(lang) {
  const name = (lang || '').toLowerCase();
  return ALIASES[name] || (RULES[name] ? name : 'plain');
}

export function tokenize(code, lang) {
  const rules = RULES[languageOf(lang)] || [];
  const tokens = [];
  let plain = '';
  let i = 0;
  const flush = () => {
    if (plain) tokens.push([plain, '']);
    plain = '';
  };
  outer: while (i < code.length) {
    for (const [kind, rule] of rules) {
      rule.lastIndex = i;
      const match = rule.exec(code);
      if (!match || !match[0]) continue;
      let text = match[0];
      let tokenKind = kind;
      if (kind === 'w') {
        // Words: keywords stand out, the rest stays plain
        tokenKind = PYTHON_KEYWORDS.has(text) ? 'k' : '';
      }
      if (tokenKind) {
        flush();
        tokens.push([text, tokenKind]);
      } else {
        plain += text;
      }
      i += text.length;
      continue outer;
    }
    plain += code[i];
    i += 1;
  }
  flush();
  return tokens;
}

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
export const escapeHtml = (text) => text.replace(/[&<>"]/g, (ch) => ESCAPES[ch]);

export function highlightHtml(code, lang) {
  return tokenize(code, lang)
    .map(([text, kind]) => (kind ? `<span class="hl-${kind}">${escapeHtml(text)}</span>` : escapeHtml(text)))
    .join('');
}

export function Highlight({ code, lang }) {
  return tokenize(code, lang).map(([text, kind], i) => (kind ? <span key={i} className={`hl-${kind}`}>{text}</span> : text));
}
