// Node smoke test for js/pylevate-ai-core.js — run: node tests/js/ai_core_smoke.mjs
import assert from 'node:assert/strict';
import {
  sseEvents, openAIEvents, anthropicEvents, assembleMessage,
  buildOpenAIRequest, buildAnthropicRequest,
  parseOpenAIResponse, parseAnthropicResponse,
  cosineSimilarity, chunkText,
} from '../../js/pylevate-ai-core.js';

// Fake a fetch Response whose body yields the given byte chunks.
function fakeResponse(chunks) {
  let i = 0;
  return {
    body: {
      getReader() {
        return {
          read: async () => (i < chunks.length
            ? { done: false, value: chunks[i++] }
            : { done: true, value: undefined }),
          releaseLock() {},
        };
      },
    },
  };
}

const enc = new TextEncoder();

// --- SSE parser: frames split mid-frame and mid-multibyte-char ---------------
{
  const full = 'data: {"a": "héllo"}\n\nevent: ping\ndata: {}\n\n';
  const bytes = enc.encode(full);
  // Split inside the 2-byte é and inside the second frame
  const chunks = [bytes.slice(0, 12), bytes.slice(12, 13), bytes.slice(13, 30), bytes.slice(30)];
  const frames = [];
  for await (const f of sseEvents(fakeResponse(chunks))) frames.push(f);
  assert.equal(frames.length, 2);
  assert.equal(JSON.parse(frames[0].data).a, 'héllo');
  assert.equal(frames[1].event, 'ping');
}

// --- SSE parser: CRLF-delimited stream (spec-permitted) ------------------------
{
  const full = 'data: {"a": 1}\r\n\r\ndata: {"a": 2}\r\n\r\n';
  const bytes = enc.encode(full);
  // Split so a chunk ends exactly on the '\r' of a CRLF pair
  const crIndex = full.indexOf('\r');
  const chunks = [bytes.slice(0, crIndex + 1), bytes.slice(crIndex + 1)];
  const frames = [];
  for await (const f of sseEvents(fakeResponse(chunks))) frames.push(f);
  assert.equal(frames.length, 2);
  assert.equal(JSON.parse(frames[0].data).a, 1);
  assert.equal(JSON.parse(frames[1].data).a, 2);
}

// --- OpenAI stream over CRLF: [DONE] termination still works ---------------------
{
  const sse = 'data: {"choices":[{"delta":{"content":"hi"}}]}\r\n\r\ndata: [DONE]\r\n\r\n';
  const { message } = await assembleMessage(openAIEvents(sseEvents(fakeResponse([enc.encode(sse)]))));
  assert.equal(message.content, 'hi');
  assert.equal(message.finish_reason, 'stop');
}

// --- OpenAI stream: tokens + [DONE] ------------------------------------------
{
  const sse = [
    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
    'data: [DONE]\n\n',
  ].join('');
  const tokens = [];
  const { message } = await assembleMessage(
    openAIEvents(sseEvents(fakeResponse([enc.encode(sse)]))),
    { on_token: (t) => tokens.push(t) },
  );
  assert.equal(message.content, 'Hello');
  assert.deepEqual(tokens, ['Hel', 'lo']);
  assert.equal(message.finish_reason, 'stop');
  assert.equal(message.tool_calls, null);
}

// --- OpenAI stream: incremental tool-call args --------------------------------
{
  const sse = [
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"calc"}}]}}]}\n\n',
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"x\\":"}}]}}]}\n\n',
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"42}"}}]}}]}\n\n',
    'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
    'data: [DONE]\n\n',
  ].join('');
  const { message } = await assembleMessage(openAIEvents(sseEvents(fakeResponse([enc.encode(sse)]))));
  assert.equal(message.finish_reason, 'tool_calls');
  assert.equal(message.tool_calls.length, 1);
  assert.equal(message.tool_calls[0].id, 'call_1');
  assert.equal(message.tool_calls[0].function.name, 'calc');
  assert.deepEqual(JSON.parse(message.tool_calls[0].function.arguments), { x: 42 });
}

// --- Anthropic stream: text + tool_use + stop mapping -------------------------
{
  const sse = [
    'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n',
    'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Sure."}}\n\n',
    'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu_1","name":"calc"}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"x\\": 4"}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"2}"}}\n\n',
    'event: content_block_stop\ndata: {"type":"content_block_stop","index":1}\n\n',
    'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":5}}\n\n',
    'event: message_stop\ndata: {"type":"message_stop"}\n\n',
  ].join('');
  const { message } = await assembleMessage(anthropicEvents(sseEvents(fakeResponse([enc.encode(sse)]))));
  assert.equal(message.content, 'Sure.');
  assert.equal(message.finish_reason, 'tool_calls');
  assert.equal(message.tool_calls[0].id, 'tu_1');
  assert.deepEqual(JSON.parse(message.tool_calls[0].function.arguments), { x: 42 });
}

// --- Request builders ----------------------------------------------------------
{
  const messages = [
    { role: 'system', content: 'be terse' },
    { role: 'user', content: 'hi' },
    { role: 'assistant', content: '', tool_calls: [{ id: 'c1', type: 'function', function: { name: 'calc', arguments: '{"x":1}' } }] },
    { role: 'tool', tool_call_id: 'c1', content: '2' },
    { role: 'tool', tool_call_id: 'c2', content: '3' },
  ];
  const tools = [{ name: 'calc', description: 'd', parameters: { type: 'object' } }];

  const oa = buildOpenAIRequest(messages, { model: 'm', system: 'sys', tools });
  assert.equal(oa.messages[0].role, 'system');
  assert.equal(oa.messages[0].content, 'sys');
  assert.equal(oa.tools[0].type, 'function');
  assert.equal(oa.tools[0].function.name, 'calc');

  const an = buildAnthropicRequest(messages, { model: 'm', tools });
  assert.equal(an.system, 'be terse');            // system hoisted out of messages
  assert.equal(an.max_tokens, 4096);              // required default
  assert.equal(an.tools[0].input_schema.type, 'object');
  const assistantMsg = an.messages.find((m) => m.role === 'assistant');
  assert.equal(assistantMsg.content.find((b) => b.type === 'tool_use').id, 'c1');
  // Both tool results folded into ONE user message
  const resultMsgs = an.messages.filter((m) => Array.isArray(m.content) && m.content.some((b) => b.type === 'tool_result'));
  assert.equal(resultMsgs.length, 1);
  assert.equal(resultMsgs[0].content.length, 2);
  assert.ok(!an.messages.some((m) => m.role === 'system' || m.role === 'tool'));
}

// --- Non-streaming parsers -------------------------------------------------------
{
  const oa = parseOpenAIResponse({
    id: 'x', choices: [{ message: { content: 'hi' }, finish_reason: 'stop' }], usage: { total_tokens: 3 },
  });
  assert.equal(oa.content, 'hi');
  const an = parseAnthropicResponse({
    id: 'y', stop_reason: 'end_turn',
    content: [{ type: 'text', text: 'a' }, { type: 'tool_use', id: 't', name: 'n', input: { q: 1 } }],
  });
  assert.equal(an.content, 'a');
  assert.equal(an.finish_reason, 'stop');
  assert.deepEqual(JSON.parse(an.tool_calls[0].function.arguments), { q: 1 });
}

// --- Helpers ------------------------------------------------------------------------
assert.ok(Math.abs(cosineSimilarity([1, 0], [1, 0]) - 1) < 1e-9);
assert.ok(Math.abs(cosineSimilarity([1, 0], [0, 1])) < 1e-9);
assert.equal(cosineSimilarity([0, 0], [1, 1]), 0);

const chunks = chunkText('para one.\n\npara two.\n\n' + 'long sentence. '.repeat(60), 100);
assert.ok(chunks.length > 2);
assert.ok(chunks.every((c) => c.length <= 120)); // small tolerance over maxChars
assert.equal(chunkText('short', 100).length, 1);

console.log('ai_core_smoke: all assertions passed');
