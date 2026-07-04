// jsdom harness for the browser runtime (js/pylevate-runtime.js + chat
// components) — run: node tests/js/runtime_jsdom.mjs
// Needs the repo-root devDependencies: npm install (preact, preact-router,
// @preact/signals, jsdom).
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { JSDOM } from 'jsdom';

register('./css-stub-loader.mjs', import.meta.url);

// ---------------------------------------------------------------------------
// Browser globals must exist BEFORE the runtime is imported: its dev-mode
// branch registers window listeners at module scope, and Store registration
// is gated on __PYLEVATE_DEV__.
// ---------------------------------------------------------------------------
const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
  url: 'https://app.test/',
  pretendToBeVisual: true,
});

globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.sessionStorage = dom.window.sessionStorage;
globalThis.history = dom.window.history;
globalThis.location = dom.window.location;
globalThis.Event = dom.window.Event;
globalThis.CustomEvent = dom.window.CustomEvent;
globalThis.MouseEvent = dom.window.MouseEvent;
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
// preact-router registers its popstate/click handlers via bare global calls.
globalThis.addEventListener = dom.window.addEventListener.bind(dom.window);
globalThis.removeEventListener = dom.window.removeEventListener.bind(dom.window);
globalThis.__PYLEVATE_DEV__ = true;

const {
  h, render, App, Router, page, Store, mount, signal,
} = await import('../../js/pylevate-runtime.js');
const {
  MessageBubble, ToolCallCard,
} = await import('../../js/pylevate-chat-runtime.js');

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function freshContainer() {
  document.body.innerHTML = '<div id="app"></div>';
  return document.getElementById('app');
}

function clickLink(href) {
  const a = document.querySelector(`a[href="${href}"]`);
  assert.ok(a, `link ${href} not rendered`);
  a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
}

// ---------------------------------------------------------------------------
// mount() renders a component
// ---------------------------------------------------------------------------
{
  const target = freshContainer();
  mount(() => h('h1', null, 'hello'), '#app');
  assert.equal(target.querySelector('h1').textContent, 'hello');
  render(null, target);
}

// NOTE on test order: preact-router keeps a module-global custom history that
// is set by the first Router mounted with a `history` prop and never cleared.
// Root-path routing tests must therefore run BEFORE the <base href> tests.

// Shared routed pages for the router tests
const Home = page({ title: 'Home T', route: '/' })(
  () => h('div', null, h('h1', null, 'HOME'), h('a', { href: '/stats' }, 'to stats')),
);
const Stats = page({ title: 'Stats T', route: '/stats' })(
  () => h('h1', null, 'STATS'),
);
const routes = () => new Router([['/', Home], ['/stats', Stats]]);

// ---------------------------------------------------------------------------
// App + Router at the origin root: render, @page titles, link navigation,
// back button
// ---------------------------------------------------------------------------
{
  dom.reconfigure({ url: 'https://app.test/' });
  const target = freshContainer();
  new App({ router: routes() }).mount('#app');
  await tick();
  assert.equal(target.querySelector('h1').textContent, 'HOME');
  assert.equal(document.title, 'Home T');

  clickLink('/stats');
  await tick();
  assert.equal(target.querySelector('h1').textContent, 'STATS');
  assert.equal(document.title, 'Stats T');
  assert.equal(window.location.pathname, '/stats');

  history.back();
  await tick(); await tick();
  assert.equal(target.querySelector('h1').textContent, 'HOME');
  assert.equal(window.location.pathname, '/');
  render(null, target);
}

// ---------------------------------------------------------------------------
// <base href>: routing under a sub-path (PR #1 behavior)
// ---------------------------------------------------------------------------
{
  dom.reconfigure({ url: 'https://app.test/myapp/' });
  const base = document.createElement('base');
  base.href = '/myapp/';
  document.head.appendChild(base);

  const target = freshContainer();
  new App({ router: routes() }).mount('#app');
  await tick();
  assert.equal(target.querySelector('h1').textContent, 'HOME', 'route / must match under /myapp/');
  assert.equal(document.title, 'Home T');

  clickLink('/stats');
  await tick();
  assert.equal(target.querySelector('h1').textContent, 'STATS');
  // Address bar keeps the base prefix
  assert.equal(window.location.pathname, '/myapp/stats');

  history.back();
  await tick(); await tick();
  assert.equal(target.querySelector('h1').textContent, 'HOME');
  assert.equal(window.location.pathname, '/myapp/');
  render(null, target);

  // Boundary: '/myapplication/…' must NOT be stripped by base '/myapp'
  dom.reconfigure({ url: 'https://app.test/myapplication/stats' });
  const target2 = freshContainer();
  new App({ router: routes() }).mount('#app');
  await tick();
  assert.equal(target2.querySelector('h1'), null,
    "base '/myapp' must not strip '/myapplication/…'");
  render(null, target2);

  base.remove();
  dom.reconfigure({ url: 'https://app.test/' });
}

// ---------------------------------------------------------------------------
// Store dev rehydration: snapshot on before-reload, restore on construction,
// on_rehydrate hook resets transient state
// ---------------------------------------------------------------------------
{
  sessionStorage.clear();

  class ChatStore extends Store {
    constructor() {
      super();
      // Mirrors compiled output: signal fields assigned after super().
      this._count = signal(0);
      this._busy = signal(false);
      this.hook_calls = 0;
    }

    on_rehydrate() {
      this.hook_calls += 1;
      this._busy.value = false; // transient — must not survive a reload
    }
  }

  const first = new ChatStore();
  await tick();
  first._count.value = 5;
  first._busy.value = true;

  window.dispatchEvent(new Event('pylevate:before-reload'));
  const raw = sessionStorage.getItem('__pylevate_state__');
  assert.ok(raw, 'snapshot written on before-reload');
  assert.equal(JSON.parse(raw).ChatStore._count, 5);
  assert.equal(JSON.parse(raw).ChatStore._busy, true);

  // "Reload": a fresh instance rehydrates on a microtask.
  const second = new ChatStore();
  await tick();
  assert.equal(second._count.value, 5, 'persisted signal restored');
  assert.equal(second._busy.value, false, 'on_rehydrate reset the transient flag');
  assert.equal(second.hook_calls, 1);
  assert.equal(sessionStorage.getItem('__pylevate_state__'), null, 'snapshot consumed');
}

// A throwing on_rehydrate must not derail cleanup or the restore itself.
{
  sessionStorage.setItem('__pylevate_state__', JSON.stringify({ BadStore: { _x: 9 } }));

  class BadStore extends Store {
    constructor() {
      super();
      this._x = signal(0);
    }

    on_rehydrate() {
      throw new Error('user hook bug');
    }
  }

  const errors = [];
  const origError = console.error;
  console.error = (...args) => errors.push(args.join(' '));
  const store = new BadStore();
  await tick();
  console.error = origError;

  assert.equal(store._x.value, 9, 'values restored despite throwing hook');
  assert.equal(sessionStorage.getItem('__pylevate_state__'), null,
    'snapshot cleanup still ran');
  assert.ok(errors.some((e) => e.includes('on_rehydrate')), 'hook failure reported');
}

// ---------------------------------------------------------------------------
// Chat components: markdown on completed messages, plain text while streaming
// ---------------------------------------------------------------------------
{
  const target = freshContainer();
  render(h(MessageBubble, { role: 'assistant', content: 'hi **bold** `c`' }), target);
  const md = target.querySelector('.pl-md');
  assert.ok(md, 'completed assistant message renders markdown');
  assert.ok(md.innerHTML.includes('<strong>bold</strong>'));
  assert.ok(md.innerHTML.includes('<code>c</code>'));
  render(null, target);

  render(h(MessageBubble, { role: 'assistant', content: 'hi **bold**', streaming: true }), target);
  assert.equal(target.querySelector('.pl-md'), null, 'streaming renders plain text');
  assert.ok(target.textContent.includes('**bold**'));
  assert.ok(target.querySelector('.pl-caret'), 'streaming caret shown');
  render(null, target);

  render(h(ToolCallCard, { name: 'calc', args: { x: 1 }, result: '42', status: 'done' }), target);
  assert.equal(target.querySelector('.pl-tool-name').textContent, 'calc');
  assert.ok(target.textContent.includes('42'));
  render(null, target);
}

console.log('runtime_jsdom: all assertions passed');
