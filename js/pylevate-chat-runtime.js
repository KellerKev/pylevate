/**
 * PyLevate chat components — out-of-the-box UI for LLM chat/agent apps.
 * Imported from Python as `from pylevate.chat import ChatWindow, ...`.
 *
 * Message shape (canonical OpenAI form, plain JSON so it Store-persists):
 *   {id, role: 'user'|'assistant'|'tool', content, tool_calls?, tool_call_id?}
 */

import { h, Fragment } from 'preact';
import { useRef, useEffect } from 'preact/hooks';
import { renderMarkdown } from './pylevate-md.js';
import './pylevate-chat.css';

/**
 * Markdown — renders markdown source as sanitized HTML.
 * Props: source
 */
export function Markdown(props) {
  return h('div', {
    className: 'pl-md',
    dangerouslySetInnerHTML: { __html: renderMarkdown(props.source || '') },
  });
}

/** TypingIndicator — three-dot pulse. */
export function TypingIndicator() {
  return h('span', { className: 'pl-typing' },
    h('span', { className: 'pl-typing-dot' }),
    h('span', { className: 'pl-typing-dot' }),
    h('span', { className: 'pl-typing-dot' }));
}

/**
 * MessageBubble — a single chat message.
 * Props: role, content, streaming, markdown (default true)
 */
export function MessageBubble(props) {
  const role = props.role || 'assistant';
  // While streaming, render plain text: re-running the markdown renderer and
  // re-parsing innerHTML over the growing buffer on every token is O(n²) per
  // reply. The final pushed message renders markdown once.
  const useMd = props.markdown !== false && role === 'assistant' && !props.streaming;
  const body = useMd
    ? h(Markdown, { source: props.content || '' })
    : (props.content || '');
  const streamingCls = props.streaming ? ' pl-streaming' : '';
  return h('div', { className: `pl-bubble pl-bubble-${role}${streamingCls}` },
    body,
    props.streaming ? h('span', { className: 'pl-caret' }) : null);
}

/**
 * ToolCallCard — collapsible display of one tool invocation.
 * Props: name, args (object|string), result (string|null),
 *        status ('running'|'done'|'error'), open
 */
export function ToolCallCard(props) {
  const status = props.status || (props.result != null ? 'done' : 'running');
  const args = typeof props.args === 'string'
    ? props.args
    : JSON.stringify(props.args ?? {}, null, 2);
  const statusEl = status === 'running'
    ? h('span', { className: 'pl-tool-spinner' })
    : h('span', { className: `pl-tool-status${status === 'error' ? ' pl-tool-status-error' : ''}` },
        status === 'error' ? 'error' : 'done');
  return h('details', { className: 'pl-tool-card', open: !!props.open },
    h('summary', { className: 'pl-tool-summary' },
      h('span', null, '🔧'),
      h('span', { className: 'pl-tool-name' }, props.name || 'tool'),
      statusEl),
    h('div', { className: 'pl-tool-detail' },
      h('div', { className: 'pl-tool-label' }, 'Arguments'),
      h('pre', { className: 'pl-tool-pre' }, args),
      props.result != null ? h(Fragment, null,
        h('div', { className: 'pl-tool-label' }, 'Result'),
        h('pre', { className: 'pl-tool-pre' }, String(props.result))) : null));
}

function renderMessage(msg, useMd) {
  if (msg.role === 'tool') {
    return h('div', { className: 'pl-bubble-tool', key: msg.id ?? undefined },
      h(ToolCallCard, {
        name: msg.name || 'tool',
        args: msg.args ?? '',
        result: msg.content,
        status: msg.is_error ? 'error' : 'done',
      }));
  }
  const parts = [];
  if (msg.content || !msg.tool_calls) {
    parts.push(h(MessageBubble, { role: msg.role, content: msg.content, markdown: useMd }));
  }
  for (const tc of msg.tool_calls || []) {
    parts.push(h('div', { className: 'pl-bubble-tool' },
      h(ToolCallCard, {
        name: tc.function && tc.function.name,
        args: (tc.function && tc.function.arguments) || '',
        result: tc.result ?? null,
        status: tc.status || 'done',
      })));
  }
  return h(Fragment, { key: msg.id ?? undefined }, parts);
}

/**
 * MessageList — scrollable message transcript with smart autoscroll.
 * Props: messages (array), streaming_text (string|null), streaming (bool),
 *        markdown (default true), empty_text
 */
export function MessageList(props) {
  const containerRef = useRef(null);
  const stickRef = useRef(true);
  const messages = props.messages || [];
  const useMd = props.markdown !== false;

  const onScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  useEffect(() => {
    const el = containerRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, props.streaming_text, props.streaming]);

  const children = messages.map((m, i) =>
    h(Fragment, { key: m.id ?? i }, renderMessage(m, useMd)));

  if (props.streaming) {
    children.push(h(Fragment, { key: '__streaming__' },
      props.streaming_text
        ? h(MessageBubble, { role: 'assistant', content: props.streaming_text, streaming: true, markdown: useMd })
        : h('div', { className: 'pl-bubble pl-bubble-assistant' }, h(TypingIndicator, null))));
  }

  if (!children.length && props.empty_text) {
    children.push(h('div', { className: 'pl-empty', key: '__empty__' }, props.empty_text));
  }

  return h('div', { className: 'pl-message-list', ref: containerRef, onScroll }, children);
}

/**
 * ChatInput — auto-growing textarea; Enter sends, Shift+Enter adds a newline.
 * Props: on_send(text), disabled, placeholder
 */
export function ChatInput(props) {
  const taRef = useRef(null);

  const send = () => {
    const ta = taRef.current;
    if (!ta) return;
    const text = ta.value.trim();
    if (!text || props.disabled) return;
    if (props.on_send) props.on_send(text);
    ta.value = '';
    ta.style.height = 'auto';
    ta.focus();
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const onInput = (e) => {
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  };

  return h('div', { className: 'pl-chat-input' },
    h('textarea', {
      className: 'pl-chat-textarea',
      rows: 1,
      ref: taRef,
      disabled: !!props.disabled,
      placeholder: props.placeholder || 'Type a message…',
      onKeyDown,
      onInput,
    }),
    h('button', {
      className: 'pl-send-btn',
      disabled: !!props.disabled,
      onClick: send,
    }, 'Send'));
}

/**
 * ChatWindow — flex-column layout shell.
 * Props: slot_header, slot_footer (filled via ChatWindow.S.header()/footer()
 * in Python templates), children = the body.
 */
export function ChatWindow(props) {
  return h('div', { className: 'pl-chat-window' },
    props.slot_header ? h('div', { className: 'pl-chat-header' }, props.slot_header) : null,
    h('div', { className: 'pl-chat-body' }, props.children),
    props.slot_footer ? h('div', { className: 'pl-chat-footer' }, props.slot_footer) : null);
}

// Compile-time slot marker support: `ChatWindow.S.header()` in Python needs
// the attribute chain to exist at runtime only as a no-op (the compiler
// rewrites fills into slot_* props before this would ever be called).
ChatWindow.S = {
  header: () => null,
  footer: () => null,
};
