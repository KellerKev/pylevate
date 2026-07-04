"""PyLevate RAG template — embeddings-based Q&A with cited sources.

The corpus (corpus.py) is chunked and embedded once via the provider's
embeddings API; each question is embedded, the top chunks are retrieved by
cosine similarity, and the model answers from those chunks with citations.

Needs an OpenAI-compatible embeddings endpoint — e.g. Ollama with
`ollama pull nomic-embed-text`, or OpenAI's text-embedding-3-small.
"""

from pylevate import Component, Store, action, css, h, mount
from pylevate.ai import AIClient, chunk_text, cosine_similarity
from pylevate.chat import ChatInput, ChatWindow, MessageList
from pylevate.signals import signal

from corpus import CORPUS

TOP_K = 3


class RagStore(Store):
    messages = signal([])
    sources = signal([])        # [{index, text, score}] for the last answer
    chunks = signal([])
    embeddings = signal([])     # survives dev reloads — the index builds once
    streaming_text = signal(None)
    busy = signal(False)
    status = signal('')
    base_url = signal('http://localhost:11434/v1')
    chat_model = signal('llama3.2')
    embed_model = signal('nomic-embed-text')
    api_key = signal('')

    def on_rehydrate(self):
        self.busy = False
        self.streaming_text = None
        self.status = ''

    @action
    def push(self, msg):
        self.messages = [*self.messages, msg]

    @action
    def append_token(self, t):
        self.streaming_text = (self.streaming_text or '') + t

    def client(self):
        return AIClient(base_url=self.base_url, api_key=self.api_key)

    async def ensure_index(self):
        if len(self.embeddings) > 0:
            return
        self.status = 'Indexing corpus…'
        pieces = chunk_text(CORPUS, 500)
        vectors = await self.client().embeddings(pieces, model=self.embed_model)
        self.chunks = pieces
        self.embeddings = vectors
        self.status = ''

    async def ask(self, question):
        if self.busy:
            return
        self.push({'id': str(Date.now()), 'role': 'user', 'content': question})
        self.busy = True
        self.streaming_text = ''
        try:
            await self.ensure_index()

            self.status = 'Retrieving…'
            q_vecs = await self.client().embeddings([question], model=self.embed_model)
            q_vec = q_vecs[0]
            scored = []
            for i, vec in enumerate(self.embeddings):
                scored.append({'index': i, 'score': cosine_similarity(q_vec, vec),
                               'text': self.chunks[i]})
            scored.sort(key=lambda s: -s['score'])
            # Number sources by rank so the model's citations ([1], [2], ...)
            # match the labels shown in the sources pane.
            top = []
            for rank, source in enumerate(scored[0:TOP_K]):
                top.append({**source, 'rank': rank + 1})
            self.sources = top
            self.status = ''

            context_parts = []
            for source in top:
                context_parts.append('[' + str(source['rank']) + '] ' + source['text'])
            prompt = (
                'Answer the question using ONLY the numbered context below. '
                'Cite the chunks you used like [1] or [2]. If the context is '
                'insufficient, say so.\n\nContext:\n' + '\n\n'.join(context_parts)
                + '\n\nQuestion: ' + question
            )

            reply = await self.client().chat(
                [{'role': 'user', 'content': prompt}],
                model=self.chat_model,
                on_token=lambda t: self.append_token(t),
            )
            self.push(reply)
        except Exception as e:
            self.push({'id': str(Date.now()), 'role': 'assistant',
                       'content': '**Error:** ' + str(e)})
            self.status = ''
        self.streaming_text = None
        self.busy = False


rag = RagStore()


class App(Component):

    style = css("""
        .shell { height: 100vh; max-width: 900px; margin: 0 auto; display: flex; }
        .chat-pane { flex: 1.6; min-width: 0; }
        .sources-pane {
            flex: 1; min-width: 0; border-left: 1px solid #e0e0e0;
            background: #fff; overflow-y: auto; padding: 0.75rem;
        }
        .sources-title { font-size: 0.8rem; color: #888; text-transform: uppercase;
                         letter-spacing: 0.05em; margin-bottom: 0.5rem; }
        .source { border: 1px solid #e8e8e8; border-radius: 8px;
                  margin-bottom: 0.5rem; font-size: 0.85rem; }
        .source summary { padding: 0.4rem 0.6rem; cursor: pointer; color: #444; }
        .source-body { padding: 0.5rem 0.7rem; color: #555; border-top: 1px solid #eee;
                       white-space: pre-wrap; }
        .settings { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
        .settings label { font-size: 0.75rem; color: #888; }
        .settings input { border: 1px solid #d0d0d0; border-radius: 6px;
                          padding: 0.3rem 0.5rem; font-size: 0.82rem; }
        .status { font-size: 0.78rem; color: #5c6bc0; }
    """)

    def get_context(self, props):
        props['messages'] = rag.messages
        props['sources'] = rag.sources
        props['streaming_text'] = rag.streaming_text
        props['busy'] = rag.busy
        props['status_text'] = rag.status
        props['base_url'] = rag.base_url
        props['chat_model'] = rag.chat_model
        props['embed_model'] = rag.embed_model
        props['api_key'] = rag.api_key
        return props

    def ask(self, text):
        rag.ask(text)

    template = {
        h.div(Class='shell'): {
            h.div(Class='chat-pane'): {
                ChatWindow(): {
                    ChatWindow.S.header(): {
                        h.div(Class='settings'): {
                            h.label(): 'Endpoint',
                            h.input(value={'base_url'},
                                    onInput={'e => rag.base_url = e.target.value'}): None,
                            h.label(): 'Chat',
                            h.input(value={'chat_model'},
                                    onInput={'e => rag.chat_model = e.target.value'}): None,
                            h.label(): 'Embed',
                            h.input(value={'embed_model'},
                                    onInput={'e => rag.embed_model = e.target.value'}): None,
                            h.label(): 'Key',
                            h.input(type='password', placeholder='(optional)', value={'api_key'},
                                    onInput={'e => rag.api_key = e.target.value'}): None,
                            h.span(Class='status'): '[[status_text]]',
                        },
                    },
                    MessageList(
                        messages={'messages'},
                        streaming_text={'streaming_text'},
                        streaming={'busy'},
                        empty_text='Ask about the corpus — e.g. "How does routing work?"',
                    ): None,
                    ChatInput(on_send={'self.ask'}, disabled={'busy'},
                              placeholder='Ask the corpus…'): None,
                }
            },
            h.div(Class='sources-pane'): {
                h.div(Class='sources-title'): 'Sources (last answer)',
                h.Template(For='source in sources'): {
                    h.details(Class='source', key={'source["rank"]'}): {
                        h.summary(): '[[source["rank"]]] · score [[source["score"]]]',
                        h.div(Class='source-body'): '[[source["text"]]]',
                    },
                },
            },
        }
    }


mount(App, '#app')
