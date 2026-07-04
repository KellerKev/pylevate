// Node smoke test for js/pylevate-md.js — run: node tests/js/md_smoke.mjs
import assert from 'node:assert/strict';
import { renderMarkdown, sanitizeUrl, escapeHtml } from '../../js/pylevate-md.js';

// --- XSS matrix -------------------------------------------------------------
const hostile = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '[click](javascript:alert(1))',
  '[click](data:text/html,<script>alert(1)</script>)',
  '[click](JaVaScRiPt:alert(1))',
  '[click](javascript:alert(1))',
  '`<iframe src=evil>`',
];
for (const input of hostile) {
  const html = renderMarkdown(input);
  assert.ok(!html.includes('<script'), `script survived: ${input} -> ${html}`);
  assert.ok(!html.includes('<img'), `img survived: ${input} -> ${html}`);
  assert.ok(!html.includes('<iframe'), `iframe survived: ${input} -> ${html}`);
  assert.ok(!/href="[^"]*javascript:/i.test(html), `js href survived: ${input} -> ${html}`);
  assert.ok(!/href="[^"]*data:/i.test(html), `data href survived: ${input} -> ${html}`);
}

assert.equal(sanitizeUrl('javascript:alert(1)'), '#');
assert.equal(sanitizeUrl('  https://ok.example/a?b=1 '), 'https://ok.example/a?b=1');
assert.equal(sanitizeUrl('//cdn.example/x.js'), 'https://cdn.example/x.js');
assert.equal(sanitizeUrl('/local/path'), '/local/path');
assert.equal(escapeHtml('<a b="c">'), '&lt;a b=&quot;c&quot;&gt;');

// --- feature matrix ----------------------------------------------------------
let html = renderMarkdown('# Title\n\nHello **bold** and *em* and `code`.');
assert.ok(html.includes('<h1>Title</h1>'));
assert.ok(html.includes('<strong>bold</strong>'));
assert.ok(html.includes('<em>em</em>'));
assert.ok(html.includes('<code>code</code>'));

html = renderMarkdown('```python\nprint("hi < there")\n```');
assert.ok(html.includes('<pre><code class="language-python">'));
assert.ok(html.includes('print(&quot;hi &lt; there&quot;)'));

// Code block content must not get inline formatting
html = renderMarkdown('```\n**not bold** [not](a-link)\n```');
assert.ok(!html.includes('<strong>'));
assert.ok(!html.includes('<a '));

// Unterminated fence while streaming still renders as a code block
html = renderMarkdown('start\n\n```js\nconst x = 1;');
assert.ok(html.includes('<pre><code class="language-js">const x = 1;</code></pre>'));

// Hostile language token dropped
html = renderMarkdown('```"><script>\ncode\n```');
assert.ok(!html.includes('<script'));
assert.ok(html.includes('<pre><code>'));

html = renderMarkdown('- one\n- two\n\n1. first\n2. second');
assert.ok(html.includes('<ul><li>one</li><li>two</li></ul>'));
assert.ok(html.includes('<ol><li>first</li><li>second</li></ol>'));

html = renderMarkdown('> quoted text');
assert.ok(html.includes('<blockquote>quoted text</blockquote>'));

html = renderMarkdown('line one\nline two\n\npara two');
assert.ok(html.includes('<p>line one<br>line two</p>'));
assert.ok(html.includes('<p>para two</p>'));

html = renderMarkdown('above\n\n---\n\nbelow');
assert.ok(html.includes('<hr>'));

html = renderMarkdown('[good](https://example.com/x)');
assert.ok(html.includes('href="https://example.com/x"'));
assert.ok(html.includes('rel="noopener noreferrer"'));

assert.equal(renderMarkdown(''), '');
assert.equal(renderMarkdown(null), '');

console.log('md_smoke: all assertions passed');
