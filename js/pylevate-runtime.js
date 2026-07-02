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
export { Router, Route, Link, route } from 'preact-router';

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
 * Store base class — signals-based cross-component state.
 */
export class Store {
  constructor() {
    // Stores are singletons by convention
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
