/**
 * PyLevate AI runtime — browser LLM client for OpenAI-compatible and
 * Anthropic APIs. Imported from Python as `from pylevate.ai import AIClient`.
 *
 * Python-facing conventions (the compiler turns kwargs into a trailing
 * options object, so every method is (required, opts)):
 *   client = AIClient(base_url='http://localhost:11434/v1', model='llama3.2')
 *   reply  = await client.chat(messages, on_token=lambda t: store.push(t))
 * Callbacks MUST be lambdas — bare method references lose `this`.
 *
 * base_url starting with '/' (e.g. '/api/llm') selects dev-server proxy mode:
 * same-origin requests, no API key in the browser; the proxy attaches it.
 */

import {
  sseEvents, openAIEvents, anthropicEvents, assembleMessage,
  buildOpenAIRequest, buildAnthropicRequest,
  parseOpenAIResponse, parseAnthropicResponse,
  cosineSimilarity, chunkText,
} from './pylevate-ai-core.js';

export class AIError extends Error {
  constructor(message, opts = {}) {
    super(message);
    this.name = 'AIError';
    this.status = opts.status ?? null;
    this.code = opts.code ?? null;
    this.provider = opts.provider ?? null;
  }
}

/**
 * Tool spec helper/validator: tool({name, description, parameters, handler}).
 * Returns the spec unchanged so specs read declaratively from Python.
 */
export function tool(spec) {
  if (!spec || !spec.name) throw new AIError("tool() requires a 'name'");
  if (typeof spec.handler !== 'function') {
    throw new AIError(`tool '${spec.name}' requires a 'handler' function`);
  }
  return {
    name: spec.name,
    description: spec.description || '',
    parameters: spec.parameters || { type: 'object', properties: {} },
    handler: spec.handler,
  };
}

const ANTHROPIC_DEFAULT_BASE = 'https://api.anthropic.com';

export class AIClient {
  constructor(config = {}) {
    this.base_url = (config.base_url || 'https://api.openai.com/v1').replace(/\/+$/, '');
    this.api_key = config.api_key || '';
    this.model = config.model || '';
    this.system = config.system || null;
    this.max_tokens = config.max_tokens || null;
    this.headers = config.headers || {};
    this.proxy = this.base_url.startsWith('/');
    this.provider = config.provider
      || (this.base_url.includes('anthropic.com') ? 'anthropic' : 'openai');
  }

  _headers() {
    const headers = { 'Content-Type': 'application/json', ...this.headers };
    if (this.proxy) {
      headers['X-Pylevate-Provider'] = this.provider;
      return headers; // key lives server-side
    }
    if (this.provider === 'anthropic') {
      if (this.api_key) headers['x-api-key'] = this.api_key;
      headers['anthropic-version'] = '2023-06-01';
      headers['anthropic-dangerous-direct-browser-access'] = 'true';
    } else if (this.api_key) {
      headers['Authorization'] = `Bearer ${this.api_key}`;
    }
    return headers;
  }

  _endpoint(kind) {
    if (this.provider === 'anthropic') {
      const base = this.proxy ? this.base_url : (this.base_url || ANTHROPIC_DEFAULT_BASE);
      if (kind === 'chat') return `${base}/v1/messages`;
      throw new AIError('Anthropic has no embeddings endpoint — use an OpenAI-compatible provider', {
        code: 'embeddings_unsupported', provider: 'anthropic',
      });
    }
    return kind === 'chat' ? `${this.base_url}/chat/completions` : `${this.base_url}/embeddings`;
  }

  async _post(url, body, signal) {
    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this._headers(),
        body: JSON.stringify(body),
        signal,
      });
    } catch (err) {
      if (err && err.name === 'AbortError') throw err;
      throw new AIError(
        `Request to ${url} failed (${err.message}). If this is a CORS error, `
        + `try the dev-server proxy: AIClient(base_url='/api/llm', ...)`,
        { code: 'network_error', provider: this.provider },
      );
    }
    if (!response.ok) {
      let detail = '';
      let code = null;
      try {
        const payload = await response.json();
        detail = (payload.error && payload.error.message) || JSON.stringify(payload);
        code = payload.error && (payload.error.code || payload.error.type);
      } catch (e) { /* non-JSON error body */ }
      throw new AIError(`${this.provider} request failed (${response.status}): ${detail}`, {
        status: response.status, code, provider: this.provider,
      });
    }
    return response;
  }

  _mergeOpts(opts) {
    return {
      ...opts,
      model: opts.model || this.model,
      system: opts.system ?? this.system,
      max_tokens: opts.max_tokens || this.max_tokens,
    };
  }

  /**
   * Streaming chat completion. Returns the assembled assistant message
   * {id, role, content, tool_calls?, finish_reason, usage}.
   */
  async chat(messages, opts = {}) {
    const merged = this._mergeOpts(opts);
    const stream = merged.stream !== false;
    const anthropic = this.provider === 'anthropic';
    const body = anthropic
      ? buildAnthropicRequest(messages, { ...merged, stream })
      : buildOpenAIRequest(messages, { ...merged, stream });
    const response = await this._post(this._endpoint('chat'), body, merged.signal);

    const contentType = (response.headers.get('Content-Type') || '');
    if (!stream || !contentType.includes('text/event-stream')) {
      const json = await response.json();
      const message = anthropic ? parseAnthropicResponse(json) : parseOpenAIResponse(json);
      if (merged.on_token && message.content) merged.on_token(message.content);
      return message;
    }

    const frames = sseEvents(response);
    const events = anthropic ? anthropicEvents(frames) : openAIEvents(frames);
    const { message } = await assembleMessage(events, {
      on_token: merged.on_token,
      on_event: merged.on_event,
    });
    return message;
  }

  /** Non-streaming one-shot completion; accepts a prompt string or messages. */
  async complete(promptOrMessages, opts = {}) {
    const messages = typeof promptOrMessages === 'string'
      ? [{ role: 'user', content: promptOrMessages }]
      : promptOrMessages;
    const message = await this.chat(messages, { ...opts, stream: false });
    return message.content;
  }

  /** Embeddings via the OpenAI-compatible endpoint. Returns number[][]. */
  async embeddings(texts, opts = {}) {
    const merged = this._mergeOpts(opts);
    const input = Array.isArray(texts) ? texts : [texts];
    const response = await this._post(
      this._endpoint('embeddings'),
      { model: merged.model, input },
      merged.signal,
    );
    const json = await response.json();
    return (json.data || [])
      .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
      .map((d) => d.embedding);
  }

  /**
   * Client-side agentic loop: call the model with tools, execute requested
   * tool calls, feed results back, repeat until the model stops asking.
   * Returns {messages, final} — the full transcript plus the final message.
   */
  async run_tools(messages, opts = {}) {
    const tools = opts.tools || [];
    const byName = {};
    for (const t of tools) byName[t.name] = t;
    const maxSteps = opts.max_steps || 10;
    const transcript = [...messages];
    const emit = (step) => { if (opts.on_step) opts.on_step(step); };

    for (let turn = 1; turn <= maxSteps; turn++) {
      emit({ type: 'turn', turn });
      const msg = await this.chat(transcript, {
        tools,
        on_token: opts.on_token,
        on_event: opts.on_event,
        signal: opts.signal,
        system: opts.system,
        model: opts.model,
      });
      transcript.push(msg);
      if (msg.content) emit({ type: 'assistant_text', text: msg.content });
      if (msg.finish_reason !== 'tool_calls' || !msg.tool_calls) {
        return { messages: transcript, final: msg };
      }
      const results = await Promise.all(msg.tool_calls.map(async (tc) => {
        const name = tc.function.name;
        let args = {};
        try { args = JSON.parse(tc.function.arguments || '{}'); } catch (e) { /* keep {} */ }
        emit({ type: 'tool_call', id: tc.id, name, args });
        let result;
        let isError = false;
        const spec = byName[name];
        if (!spec) {
          result = `Unknown tool: ${name}`;
          isError = true;
        } else {
          try {
            result = await spec.handler(args);
          } catch (err) {
            result = String(err && err.message || err);
            isError = true;
          }
        }
        const text = typeof result === 'string' ? result : JSON.stringify(result);
        emit({ type: 'tool_result', id: tc.id, name, result: text, is_error: isError });
        return {
          role: 'tool',
          tool_call_id: tc.id,
          content: text,
          ...(isError ? { is_error: true } : {}),
        };
      }));
      transcript.push(...results);
    }
    throw new AIError(`Tool loop exceeded ${maxSteps} steps`, { code: 'max_steps_exceeded' });
  }
}

export {
  cosineSimilarity as cosine_similarity,
  chunkText as chunk_text,
};
