/**
 * PyLevate AI core — pure protocol logic for the AI client.
 *
 * Zero imports on purpose: node can run this file directly for tests.
 * The canonical message format everywhere is the OpenAI chat shape:
 *   {role, content, tool_calls?: [{id, type:'function', function:{name, arguments}}], tool_call_id?}
 * The Anthropic adapter converts to/from that shape at the wire.
 */

// ---------------------------------------------------------------------------
// SSE parsing
// ---------------------------------------------------------------------------

/**
 * Parse a fetch Response body as Server-Sent Events.
 * Yields {event: string|null, data: string} per frame. Handles frames split
 * across chunks and multi-byte characters split across chunk boundaries.
 */
export async function* sseEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // The SSE spec permits CR and CRLF line endings — normalize to LF.
      // A trailing CR may be the first half of a CRLF split across chunks;
      // hold it back so it isn't misread as a lone-CR line ending.
      const heldCR = buf.endsWith('\r');
      if (heldCR) buf = buf.slice(0, -1);
      buf = buf.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      if (heldCR) buf += '\r';
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = null;
        const data = [];
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
        }
        if (data.length) yield { event, data: data.join('\n') };
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// OpenAI wire format
// ---------------------------------------------------------------------------

export function buildOpenAIRequest(messages, opts) {
  const body = {
    model: opts.model,
    messages: opts.system
      ? [{ role: 'system', content: opts.system }, ...messages]
      : messages,
    stream: opts.stream !== false,
  };
  if (opts.max_tokens) body.max_tokens = opts.max_tokens;
  if (opts.temperature != null) body.temperature = opts.temperature;
  if (opts.tools && opts.tools.length) {
    body.tools = opts.tools.map((t) => ({
      type: 'function',
      function: { name: t.name, description: t.description, parameters: t.parameters },
    }));
    if (opts.tool_choice) body.tool_choice = opts.tool_choice;
  }
  return body;
}

/**
 * Consume OpenAI SSE frames, emit normalized events:
 *   {type:'token', text} | {type:'tool_call_start', index, id, name}
 *   {type:'tool_call_delta', index, args_fragment}
 *   {type:'done', finish_reason, usage}
 */
export async function* openAIEvents(frames) {
  let finishReason = null;
  let usage = null;
  for await (const frame of frames) {
    if (frame.data === '[DONE]') break;
    let payload;
    try {
      payload = JSON.parse(frame.data);
    } catch (e) {
      continue; // tolerate keep-alive noise
    }
    if (payload.usage) usage = payload.usage;
    const choice = payload.choices && payload.choices[0];
    if (!choice) continue;
    if (choice.finish_reason) finishReason = choice.finish_reason;
    const delta = choice.delta || {};
    if (delta.content) yield { type: 'token', text: delta.content };
    for (const tc of delta.tool_calls || []) {
      if (tc.id || (tc.function && tc.function.name)) {
        yield {
          type: 'tool_call_start',
          index: tc.index ?? 0,
          id: tc.id || null,
          name: (tc.function && tc.function.name) || null,
        };
      }
      if (tc.function && tc.function.arguments) {
        yield { type: 'tool_call_delta', index: tc.index ?? 0, args_fragment: tc.function.arguments };
      }
    }
  }
  yield { type: 'done', finish_reason: finishReason || 'stop', usage };
}

export function parseOpenAIResponse(json) {
  const choice = json.choices && json.choices[0];
  const msg = (choice && choice.message) || { role: 'assistant', content: '' };
  return {
    id: json.id || null,
    role: 'assistant',
    content: msg.content || '',
    tool_calls: msg.tool_calls || null,
    finish_reason: (choice && choice.finish_reason) || 'stop',
    usage: json.usage || null,
  };
}

// ---------------------------------------------------------------------------
// Anthropic wire format
// ---------------------------------------------------------------------------

/** Convert canonical (OpenAI-shape) messages to an Anthropic Messages body. */
export function buildAnthropicRequest(messages, opts) {
  const systemParts = [];
  if (opts.system) systemParts.push(opts.system);
  const converted = [];
  let pendingToolResults = [];

  const flushToolResults = () => {
    if (pendingToolResults.length) {
      // Parallel tool results must land in ONE user message.
      converted.push({ role: 'user', content: pendingToolResults });
      pendingToolResults = [];
    }
  };

  for (const m of messages) {
    if (m.role === 'system') {
      systemParts.push(typeof m.content === 'string' ? m.content : '');
      continue;
    }
    if (m.role === 'tool') {
      pendingToolResults.push({
        type: 'tool_result',
        tool_use_id: m.tool_call_id,
        content: String(m.content ?? ''),
        ...(m.is_error ? { is_error: true } : {}),
      });
      continue;
    }
    flushToolResults();
    if (m.role === 'assistant' && m.tool_calls && m.tool_calls.length) {
      const blocks = [];
      if (m.content) blocks.push({ type: 'text', text: m.content });
      for (const tc of m.tool_calls) {
        let input = {};
        try { input = JSON.parse(tc.function.arguments || '{}'); } catch (e) { /* keep {} */ }
        blocks.push({ type: 'tool_use', id: tc.id, name: tc.function.name, input });
      }
      converted.push({ role: 'assistant', content: blocks });
    } else {
      converted.push({ role: m.role, content: m.content ?? '' });
    }
  }
  flushToolResults();

  const body = {
    model: opts.model,
    messages: converted,
    max_tokens: opts.max_tokens || 4096, // required by the API
    stream: opts.stream !== false,
  };
  if (systemParts.length) body.system = systemParts.join('\n\n');
  if (opts.temperature != null) body.temperature = opts.temperature;
  if (opts.tools && opts.tools.length) {
    body.tools = opts.tools.map((t) => ({
      name: t.name,
      description: t.description,
      input_schema: t.parameters,
    }));
  }
  return body;
}

const ANTHROPIC_STOP_MAP = {
  end_turn: 'stop',
  tool_use: 'tool_calls',
  max_tokens: 'length',
  stop_sequence: 'stop',
  refusal: 'refusal',
};

/** Consume Anthropic SSE frames, emit the same normalized events as OpenAI. */
export async function* anthropicEvents(frames) {
  let finishReason = null;
  let usage = null;
  const blocks = {}; // index -> {type, id, name}
  for await (const frame of frames) {
    let payload;
    try {
      payload = JSON.parse(frame.data);
    } catch (e) {
      continue;
    }
    switch (frame.event || payload.type) {
      case 'message_start':
        if (payload.message && payload.message.usage) usage = payload.message.usage;
        break;
      case 'content_block_start': {
        const block = payload.content_block || {};
        blocks[payload.index] = block;
        if (block.type === 'tool_use') {
          yield { type: 'tool_call_start', index: payload.index, id: block.id, name: block.name };
        }
        break;
      }
      case 'content_block_delta': {
        const delta = payload.delta || {};
        if (delta.type === 'text_delta' && delta.text) {
          yield { type: 'token', text: delta.text };
        } else if (delta.type === 'input_json_delta' && delta.partial_json) {
          yield { type: 'tool_call_delta', index: payload.index, args_fragment: delta.partial_json };
        }
        break;
      }
      case 'message_delta':
        if (payload.delta && payload.delta.stop_reason) {
          finishReason = ANTHROPIC_STOP_MAP[payload.delta.stop_reason] || payload.delta.stop_reason;
        }
        if (payload.usage) usage = { ...usage, ...payload.usage };
        break;
      case 'error':
        yield { type: 'error', error: payload.error || payload };
        return;
      default:
        break; // ping, content_block_stop, message_stop
    }
  }
  yield { type: 'done', finish_reason: finishReason || 'stop', usage };
}

/** Convert a non-streaming Anthropic response to the canonical message. */
export function parseAnthropicResponse(json) {
  let content = '';
  const toolCalls = [];
  for (const block of json.content || []) {
    if (block.type === 'text') content += block.text;
    else if (block.type === 'tool_use') {
      toolCalls.push({
        id: block.id,
        type: 'function',
        function: { name: block.name, arguments: JSON.stringify(block.input || {}) },
      });
    }
  }
  return {
    id: json.id || null,
    role: 'assistant',
    content,
    tool_calls: toolCalls.length ? toolCalls : null,
    finish_reason: ANTHROPIC_STOP_MAP[json.stop_reason] || json.stop_reason || 'stop',
    usage: json.usage || null,
  };
}

// ---------------------------------------------------------------------------
// Streaming assembly: normalized events -> final assistant message
// ---------------------------------------------------------------------------

/**
 * Accumulate normalized events into the final assistant message.
 * Returns {message, finish_reason, usage}. Calls opts.on_token / opts.on_event.
 */
export async function assembleMessage(events, opts = {}) {
  let content = '';
  let finishReason = 'stop';
  let usage = null;
  const toolCalls = {}; // index -> {id, name, args}
  for await (const ev of events) {
    if (opts.on_event) opts.on_event(ev);
    switch (ev.type) {
      case 'token':
        content += ev.text;
        if (opts.on_token) opts.on_token(ev.text);
        break;
      case 'tool_call_start': {
        const tc = toolCalls[ev.index] || (toolCalls[ev.index] = { id: null, name: null, args: '' });
        if (ev.id) tc.id = ev.id;
        if (ev.name) tc.name = ev.name;
        break;
      }
      case 'tool_call_delta': {
        const tc = toolCalls[ev.index] || (toolCalls[ev.index] = { id: null, name: null, args: '' });
        tc.args += ev.args_fragment;
        break;
      }
      case 'done':
        finishReason = ev.finish_reason;
        usage = ev.usage;
        break;
      case 'error':
        throw Object.assign(new Error(ev.error && ev.error.message || 'stream error'), { detail: ev.error });
      default:
        break;
    }
  }
  const calls = Object.keys(toolCalls).sort((a, b) => a - b).map((i) => {
    const tc = toolCalls[i];
    return {
      id: tc.id || `call_${i}`,
      type: 'function',
      function: { name: tc.name, arguments: tc.args || '{}' },
    };
  });
  if (calls.length && finishReason === 'stop') finishReason = 'tool_calls';
  return {
    message: {
      id: null,
      role: 'assistant',
      content,
      tool_calls: calls.length ? calls : null,
      finish_reason: finishReason,
      usage,
    },
    finish_reason: finishReason,
    usage,
  };
}

// ---------------------------------------------------------------------------
// Small helpers used by samples
// ---------------------------------------------------------------------------

export function cosineSimilarity(a, b) {
  let dot = 0;
  let na = 0;
  let nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/** Split text into ~max_chars chunks on paragraph, then sentence boundaries. */
export function chunkText(text, maxChars = 500) {
  const paragraphs = String(text).split(/\n\s*\n/);
  const chunks = [];
  let current = '';
  const push = () => {
    const trimmed = current.trim();
    if (trimmed) chunks.push(trimmed);
    current = '';
  };
  for (const para of paragraphs) {
    if ((current + '\n\n' + para).length <= maxChars) {
      current = current ? current + '\n\n' + para : para;
      continue;
    }
    push();
    if (para.length <= maxChars) {
      current = para;
      continue;
    }
    // Paragraph itself too long: split on sentences.
    for (const sentence of para.split(/(?<=[.!?])\s+/)) {
      if ((current + ' ' + sentence).length > maxChars) push();
      current = current ? current + ' ' + sentence : sentence;
    }
    push();
  }
  push();
  return chunks;
}
