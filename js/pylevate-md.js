/**
 * PyLevate Markdown — minimal, dependency-free markdown renderer for chat.
 *
 * Safety model: the ENTIRE input is HTML-escaped first, so no
 * attacker-controlled tag survives; every tag in the output is emitted by
 * this renderer. Link URLs go through sanitizeUrl (javascript:/data: -> '#').
 *
 * Supported: #–###### headings, paragraphs, **bold**, *italic*, `inline code`,
 * ``` fenced code blocks (language class whitelisted), [text](url) links,
 * > blockquotes, -/* unordered + 1. ordered lists (single level), --- hr,
 * single newline -> <br> inside paragraphs.
 * Intentionally unsupported: tables, nested lists, images, raw HTML.
 *
 * Zero imports on purpose — node can run this file directly for tests.
 */

export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function sanitizeUrl(url) {
  // Strip whitespace and ASCII control chars that could hide a scheme.
  const cleaned = String(url).trim().replace(/[\x00-\x1f\x7f]/g, '');
  const lower = cleaned.toLowerCase();
  if (lower.startsWith('http://') || lower.startsWith('https://')
      || lower.startsWith('mailto:') || lower.startsWith('#')
      || lower.startsWith('/') || lower.startsWith('./')) {
    // Protocol-relative (//host) is ambiguous — force https.
    if (cleaned.startsWith('//')) return 'https:' + cleaned;
    return cleaned;
  }
  return '#';
}

const LANG_RE = /^[a-zA-Z0-9_+-]{0,32}$/;

function renderInline(text) {
  // Inline code first: its content must skip all other inline transforms.
  const codeSpans = [];
  text = text.replace(/`([^`\n]+)`/g, (m, code) => {
    codeSpans.push(`<code>${code}</code>`);
    return `\x00IC${codeSpans.length - 1}\x00`;
  });

  // Links. The input is already escaped, so brackets/parens are literal.
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) =>
    `<a href="${sanitizeUrl(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`);

  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

  return text.replace(/\x00IC(\d+)\x00/g, (m, i) => codeSpans[Number(i)]);
}

export function renderMarkdown(source) {
  if (source == null || source === '') return '';
  let src = escapeHtml(source).replace(/\r\n/g, '\n');

  // Extract fenced code blocks before any other processing.
  const codeBlocks = [];
  src = src.replace(/```([^\n]*)\n([\s\S]*?)(?:```|$)/g, (m, lang, code) => {
    lang = lang.trim();
    const cls = LANG_RE.test(lang) && lang ? ` class="language-${lang}"` : '';
    codeBlocks.push(`<pre><code${cls}>${code.replace(/\n$/, '')}</code></pre>`);
    return `\x00CB${codeBlocks.length - 1}\x00`;
  });

  const out = [];
  const lines = src.split('\n');
  let paragraph = [];
  let list = null; // {tag, items}

  const flushParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${paragraph.map(renderInline).join('<br>')}</p>`);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      out.push(`<${list.tag}>${list.items.map((i) => `<li>${renderInline(i)}</li>`).join('')}</${list.tag}>`);
      list = null;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const block = /^\x00CB(\d+)\x00$/.exec(trimmed);
    if (block) {
      flushParagraph(); flushList();
      out.push(codeBlocks[Number(block[1])]);
      continue;
    }
    if (trimmed === '') {
      flushParagraph(); flushList();
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flushParagraph(); flushList();
      const level = heading[1].length;
      out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }
    if (/^---+$/.test(trimmed)) {
      flushParagraph(); flushList();
      out.push('<hr>');
      continue;
    }
    // Note: input is escaped, so blockquote markers arrive as '&gt;'.
    if (trimmed.startsWith('&gt;')) {
      flushParagraph(); flushList();
      out.push(`<blockquote>${renderInline(trimmed.slice(4).trim())}</blockquote>`);
      continue;
    }
    const ul = /^[-*]\s+(.*)$/.exec(trimmed);
    if (ul) {
      flushParagraph();
      if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
      list.items.push(ul[1]);
      continue;
    }
    const ol = /^\d+\.\s+(.*)$/.exec(trimmed);
    if (ol) {
      flushParagraph();
      if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; }
      list.items.push(ol[1]);
      continue;
    }
    flushList();
    paragraph.push(trimmed);
  }
  flushParagraph(); flushList();

  return out.join('\n');
}
