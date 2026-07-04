/**
 * PyLevate App Runtime — Re-exports Preact + Signals.
 * Users import from 'pylevate', never from 'preact' directly.
 */

// import-then-export (not `export ... from`): mount/state/createTag below
// need local bindings, which pure re-exports don't create.
import { h, render, Component, Fragment, createRef } from 'preact';
import { signal, computed, effect, batch } from '@preact/signals';

export { h, render, Component, Fragment, createRef };
export { signal, computed, effect, batch };
export { useState, useEffect, useRef, useMemo, useCallback } from 'preact/hooks';
// preact-router's Router component is kept internal — PyLevate's own Router
// class (below) is the public routing API. Route/Link/route stay re-exported.
import PreactRouter, { Route, Link, route } from 'preact-router';
export { Route, Link, route };

/**
 * Create a reactive state signal with getter/setter semantics.
 * In compiled output, state(x) becomes signal(x) with property accessors.
 */
export function state(initial) {
  return signal(initial);
}

/**
 * CSS module helper — returns class map at runtime.
 * Actual scoping is done at compile time; this is the runtime no-op.
 */
export function css() {
  return null;
}

/**
 * SlotsEnum — compile-time only, no runtime behavior needed.
 */
export class SlotsEnum {}

/**
 * Tag — base class for semantic custom tags. Compiled to createTag() at build time.
 */
export class Tag {}

/**
 * Tag factory — creates a functional component for semantic tags.
 */
export function createTag(tagName, identClass) {
  return function TagComponent(props) {
    const { children, className, Tag: overrideTag, ...rest } = props || {};
    const tag = overrideTag || tagName;
    const cls = identClass + (className ? ' ' + className : '');
    return h(tag, { className: cls, ...rest }, children);
  };
}

/**
 * Decorator stubs — these are compile-time only.
 * The compiler transforms @action → batch(), @computed → getter, @effect → effect().
 * These exports exist so the import doesn't fail at runtime.
 */
export function action(fn) { return fn; }

/**
 * Dev-only store state persistence across full reloads.
 *
 * __PYLEVATE_DEV__ is an esbuild define ("true" in dev, "false" in
 * production), so all of this is tree-shaken out of production bundles.
 * On reload the HMR client dispatches 'pylevate:before-reload'; signal
 * values of every registered store are snapshotted to sessionStorage and
 * restored right after the store is reconstructed on the next load.
 * Only JSON-serializable values survive; others are silently skipped.
 */
const __storeRegistry = new Map();
const __STATE_KEY = '__pylevate_state__';

function __isSignal(v) {
  return v && typeof v === 'object' && 'value' in v && typeof v.subscribe === 'function';
}

function __snapshotStores() {
  const snapshot = {};
  for (const [name, store] of __storeRegistry) {
    const values = {};
    for (const key of Object.keys(store)) {
      const v = store[key];
      if (!__isSignal(v)) continue;
      try {
        values[key] = JSON.parse(JSON.stringify(v.value));
      } catch (e) { /* non-serializable — skip */ }
    }
    snapshot[name] = values;
  }
  try {
    sessionStorage.setItem(__STATE_KEY, JSON.stringify(snapshot));
  } catch (e) { /* storage unavailable — skip */ }
}

function __rehydrateStore(name, store) {
  let snapshot;
  try {
    const raw = sessionStorage.getItem(__STATE_KEY);
    if (!raw) return;
    snapshot = JSON.parse(raw);
  } catch (e) {
    return;
  }
  const values = snapshot[name];
  if (!values) return;
  for (const key of Object.keys(values)) {
    const v = store[key];
    if (__isSignal(v)) v.value = values[key];
  }
  delete snapshot[name];
  try {
    if (Object.keys(snapshot).length === 0) {
      sessionStorage.removeItem(__STATE_KEY);
    } else {
      sessionStorage.setItem(__STATE_KEY, JSON.stringify(snapshot));
    }
  } catch (e) { /* ignore */ }
  // Post-restore hook: lets stores reset transient state (busy flags,
  // in-flight streams) that must not survive a reload. Runs after cleanup
  // and guarded, so a throwing hook can't derail rehydration bookkeeping.
  if (typeof store.on_rehydrate === 'function') {
    try {
      store.on_rehydrate();
    } catch (e) {
      console.error('[PyLevate] on_rehydrate() failed:', e);
    }
  }
}

if (typeof __PYLEVATE_DEV__ !== 'undefined' && __PYLEVATE_DEV__) {
  window.addEventListener('pylevate:before-reload', __snapshotStores);
  window.addEventListener('beforeunload', __snapshotStores);
}

/**
 * Store base class — signals-based cross-component state.
 */
export class Store {
  constructor() {
    // Stores are singletons by convention.
    if (typeof __PYLEVATE_DEV__ !== 'undefined' && __PYLEVATE_DEV__) {
      const key = this.constructor.name;
      __storeRegistry.set(key, this);
      // Subclass constructors assign signal fields after super() runs;
      // rehydrate on a microtask so those fields exist.
      queueMicrotask(() => __rehydrateStore(key, this));
    }
  }
}

/**
 * Cross-boundary event bus for hybrid mode (game ↔ UI).
 */
export { game_events } from './pylevate-events.js';

/**
 * App entry point — mounts a Preact app with optional router.
 */
export function mount(component, container) {
  const target = typeof container === 'string'
    ? document.querySelector(container)
    : container;
  render(h(component, null), target);
}

/**
 * Router — declarative route table: new Router([[path, Component], ...]).
 * Compiled from `Router([('/', Home), ('/profile/:id', Profile)])`.
 * Path params (:id) are passed to the routed component as props by
 * preact-router.
 */
export class Router {
  constructor(routes = []) {
    this.routes = routes;
  }
}

/**
 * page — curried decorator attaching route metadata to a component class.
 * Compiled from `@page(title=..., route=...)` as
 * `Cls = page({title, route})(Cls)`. Returns the same class so `export class`
 * bindings stay intact.
 */
export function page(opts = {}) {
  return function (Comp) {
    Comp.__page__ = { title: opts.title || null, route: opts.route || null };
    return Comp;
  };
}

/**
 * App — application shell: new App({router, theme, root}).
 * - router: a Router instance; renders via preact-router. Same-origin <a>
 *   clicks are intercepted by preact-router, so templates use plain h.a().
 * - theme: path to a CSS file, injected as a <link> tag.
 * - root: component to render when no router is given.
 */
// A minimal history for preact-router that hides a base path prefix, so an app
// served under /base/ routes as if it were at the origin root. Implements the
// surface preact-router uses: `location`, `listen`, `push`, `replace`.
//
// preact-router caches the first custom history it sees module-globally and
// never clears it, so mounting is only deterministic if EVERY App.mount
// supplies its own history — base '' behaves exactly like the default. Only
// the most recently created history is live: a single delegating popstate
// listener ignores stale ones from earlier mounts.
let _activeHistory = null;
let _popstateHooked = false;

function _baseHistory(base) {
  const strip = (p) => {
    // Strip only on a path-segment boundary: base '/myapp' must match
    // '/myapp' and '/myapp/x' but not '/myapplication/x'.
    const isBase = p === base || p.startsWith(base + '/');
    const s = isBase ? p.slice(base.length) : p;
    return s.charAt(0) === '/' ? s : '/' + s;
  };
  const loc = () => ({ pathname: strip(window.location.pathname), search: window.location.search });
  const listeners = [];
  const notify = () => { const l = loc(); listeners.slice().forEach((cb) => cb(l)); };
  const api = {
    get location() { return loc(); },
    listen(cb) {
      listeners.push(cb);
      return () => { const i = listeners.indexOf(cb); if (i >= 0) listeners.splice(i, 1); };
    },
    push(url) { window.history.pushState(null, '', base + url); notify(); },
    replace(url) { window.history.replaceState(null, '', base + url); notify(); },
    _notify: notify,
  };
  if (!_popstateHooked) {
    _popstateHooked = true;
    window.addEventListener('popstate', () => {
      if (_activeHistory) _activeHistory._notify();
    });
  }
  _activeHistory = api;
  return api;
}

export class App {
  constructor(opts = {}) {
    this.router = opts.router || null;
    this.theme = opts.theme || null;
    this.root = opts.root || null;
  }

  mount(container) {
    const target = typeof container === 'string'
      ? document.querySelector(container)
      : container;
    if (this.theme) this._injectTheme(this.theme);
    if (!this.router) {
      render(h(this.root, null), target);
      return;
    }
    const children = this.router.routes.map(([path, Comp]) => {
      const props = { path };
      if (path === '*') props.default = true;
      return h(Comp, props);
    });
    const onChange = (e) => {
      const Comp = e && e.current && e.current.type;
      const meta = Comp && Comp.__page__;
      if (meta && meta.title) document.title = meta.title;
    };
    // Honour a <base href> so routes match when the app is served under a
    // sub-path (e.g. a hosted preview at /.../pylevate-preview/) rather than
    // the origin root. preact-router 4.x has no `base` prop, so give it a
    // custom history whose location is stripped of the base prefix. Always
    // pass one (base '' = origin root): preact-router latches the first
    // custom history forever, so an explicit history per mount is the only
    // way to keep repeated mounts deterministic.
    const baseEl = document.querySelector('base[href]');
    const basePath = baseEl
      ? new URL(baseEl.href).pathname.replace(/\/$/, '')
      : '';
    render(h(PreactRouter, { onChange, history: _baseHistory(basePath) }, children), target);
  }

  _injectTheme(href) {
    if (document.querySelector('link[data-pylevate-theme]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.setAttribute('data-pylevate-theme', '');
    document.head.appendChild(link);
  }
}
