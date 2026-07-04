// Node smoke test for js/pylevate-ai-runtime.js — run: node tests/js/ai_runtime_smoke.mjs
// Stubs globalThis.fetch with scripted SSE responses; no network.
import assert from 'node:assert/strict';
import { AIClient, AIError, tool } from '../../js/pylevate-ai-runtime.js';

const enc = new TextEncoder();

function sseResponse(text) {
  const bytes = enc.encode(text);
  let sent = false;
  return {
    ok: true,
    headers: { get: (k) => (k.toLowerCase() === 'content-type' ? 'text/event-stream' : null) },
    body: {
      getReader: () => ({
        read: async () => (sent ? { done: true } : (sent = true, { done: false, value: bytes })),
        releaseLock() {},
      }),
    },
  };
}

function jsonResponse(obj, status = 200) {
  return {
    ok: status < 400,
    status,
    headers: { get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : null) },
    json: async () => obj,
  };
}

// --- streaming chat + headers ---------------------------------------------------
{
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return sseResponse(
      'data: {"choices":[{"delta":{"content":"hey"}}]}\n\n'
      + 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
    );
  };
  const client = new AIClient({ base_url: 'http://localhost:11434/v1', model: 'llama3.2' });
  const tokens = [];
  const msg = await client.chat([{ role: 'user', content: 'hi' }], { on_token: (t) => tokens.push(t) });
  assert.equal(msg.content, 'hey');
  assert.deepEqual(tokens, ['hey']);
  assert.equal(calls[0].url, 'http://localhost:11434/v1/chat/completions');
  // No auth header when api_key empty (Ollama)
  assert.ok(!('Authorization' in calls[0].init.headers));
}

// --- proxy mode: provider header, no key -----------------------------------------
{
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return jsonResponse({ choices: [{ message: { content: 'ok' }, finish_reason: 'stop' }] });
  };
  const client = new AIClient({ base_url: '/api/llm', model: 'gpt-4o-mini', api_key: 'should-not-be-sent' });
  await client.chat([{ role: 'user', content: 'hi' }], { stream: false });
  assert.equal(calls[0].url, '/api/llm/chat/completions');
  assert.equal(calls[0].init.headers['X-Pylevate-Provider'], 'openai');
  assert.ok(!('Authorization' in calls[0].init.headers));
}

// --- anthropic provider detection + headers ----------------------------------------
{
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    return jsonResponse({ content: [{ type: 'text', text: 'claude says hi' }], stop_reason: 'end_turn' });
  };
  const client = new AIClient({ base_url: 'https://api.anthropic.com', api_key: 'sk-ant', model: 'claude-opus-4-8' });
  assert.equal(client.provider, 'anthropic');
  const msg = await client.chat([{ role: 'user', content: 'hi' }], { stream: false });
  assert.equal(msg.content, 'claude says hi');
  assert.equal(calls[0].url, 'https://api.anthropic.com/v1/messages');
  assert.equal(calls[0].init.headers['x-api-key'], 'sk-ant');
  assert.equal(calls[0].init.headers['anthropic-version'], '2023-06-01');
  assert.equal(calls[0].init.headers['anthropic-dangerous-direct-browser-access'], 'true');
  assert.equal(calls[0].body.max_tokens, 4096);
  // embeddings unsupported on anthropic
  await assert.rejects(() => client.embeddings(['x']), (e) => e instanceof AIError && e.code === 'embeddings_unsupported');
}

// --- error mapping -------------------------------------------------------------------
{
  globalThis.fetch = async () => jsonResponse({ error: { message: 'bad key', code: 'invalid_api_key' } }, 401);
  const client = new AIClient({ base_url: 'https://api.openai.com/v1', api_key: 'nope', model: 'x' });
  await assert.rejects(
    () => client.chat([{ role: 'user', content: 'hi' }]),
    (e) => e instanceof AIError && e.status === 401 && /bad key/.test(e.message),
  );
}

// --- run_tools loop: model asks for calc, gets result, answers -------------------------
{
  let call = 0;
  globalThis.fetch = async (url, init) => {
    call += 1;
    if (call === 1) {
      return sseResponse(
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"calc"}}]}}]}\n\n'
        + 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"expr\\":\\"6*7\\"}"}}]}}]}\n\n'
        + 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n',
      );
    }
    // Second call must include the tool result in the transcript
    const body = JSON.parse(init.body);
    const toolMsg = body.messages.find((m) => m.role === 'tool');
    assert.equal(toolMsg.content, '42');
    return sseResponse(
      'data: {"choices":[{"delta":{"content":"The answer is 42."}}]}\n\n'
      + 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
    );
  };
  const client = new AIClient({ base_url: 'http://localhost:11434/v1', model: 'm' });
  const steps = [];
  const calc = tool({
    name: 'calc',
    description: 'evaluate arithmetic',
    parameters: { type: 'object', properties: { expr: { type: 'string' } } },
    handler: (args) => (args.expr === '6*7' ? '42' : 'unexpected'),
  });
  const { final, messages } = await client.run_tools(
    [{ role: 'user', content: 'what is 6*7?' }],
    { tools: [calc], on_step: (s) => steps.push(s.type) },
  );
  assert.equal(final.content, 'The answer is 42.');
  assert.ok(steps.includes('tool_call') && steps.includes('tool_result'));
  assert.equal(messages.filter((m) => m.role === 'tool').length, 1);
}

// --- run_tools: unknown tool reported as error result, loop still terminates ------------
{
  let call = 0;
  globalThis.fetch = async () => {
    call += 1;
    if (call === 1) {
      return sseResponse(
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c9","function":{"name":"nope","arguments":"{}"}}]}}]}\n\n'
        + 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n',
      );
    }
    return sseResponse(
      'data: {"choices":[{"delta":{"content":"done"}}]}\n\n'
      + 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
    );
  };
  const client = new AIClient({ base_url: 'http://x/v1', model: 'm' });
  const { messages } = await client.run_tools([{ role: 'user', content: 'go' }], { tools: [] });
  const toolMsg = messages.find((m) => m.role === 'tool');
  assert.ok(/Unknown tool/.test(toolMsg.content));
}

// --- tool() validation -----------------------------------------------------------------
assert.throws(() => tool({ name: 'x' }), AIError);
assert.throws(() => tool({ handler: () => {} }), AIError);

console.log('ai_runtime_smoke: all assertions passed');
