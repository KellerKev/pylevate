"""PyLevate chat template — a streaming LLM chatbot.

Works out of the box with a local Ollama (http://localhost:11434/v1) and any
OpenAI-compatible server (LM Studio, vLLM, OpenAI). For Anthropic, set the
base URL to https://api.anthropic.com and paste an API key. To keep keys out
of the browser entirely, run the dev server with OPENAI_API_KEY or
ANTHROPIC_API_KEY set and use the base URL /api/llm.
"""

from pylevate import Component, Store, action, css, h, mount
from pylevate.ai import AIClient
from pylevate.chat import ChatInput, ChatWindow, MessageList
from pylevate.signals import signal


class ChatStore(Store):
    # Conversation and settings survive dev-server reloads.
    messages = signal([])
    streaming_text = signal(None)
    busy = signal(False)
    base_url = signal('http://localhost:11434/v1')
    model = signal('llama3.2')
    api_key = signal('')

    def on_rehydrate(self):
        # A reload can land mid-stream; never restore in-flight state.
        self.busy = False
        self.streaming_text = None

    @action
    def push(self, msg):
        self.messages = [*self.messages, msg]

    @action
    def append_token(self, t):
        self.streaming_text = (self.streaming_text or '') + t

    def stop(self):
        if self.abort_ctrl:
            self.abort_ctrl.abort()

    async def send(self, text):
        if self.busy:
            return
        self.push({'id': str(Date.now()), 'role': 'user', 'content': text})
        self.busy = True
        self.streaming_text = ''
        # The controller is a plain attribute on purpose: it must never be
        # snapshotted into sessionStorage.
        self.abort_ctrl = AbortController()

        client = AIClient(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
        )
        try:
            reply = await client.chat(
                self.messages,
                on_token=lambda t: self.append_token(t),
                signal=self.abort_ctrl.signal,
            )
            self.push(reply)
        except Exception as e:
            if self.streaming_text:
                # Stopped mid-stream: keep what already arrived.
                self.push({'id': str(Date.now()), 'role': 'assistant',
                           'content': self.streaming_text})
            else:
                self.push({'id': str(Date.now()), 'role': 'assistant',
                           'content': '**Error:** ' + str(e)})
        self.streaming_text = None
        self.busy = False


chat = ChatStore()


class App(Component):

    style = css("""
        .shell { height: 100vh; max-width: 860px; margin: 0 auto; }
        .settings { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
        .settings label { font-size: 0.75rem; color: #888; }
        .settings input {
            border: 1px solid #d0d0d0; border-radius: 6px;
            padding: 0.3rem 0.5rem; font-size: 0.82rem;
        }
        .url-input { width: 15rem; }
        .stop-btn {
            border: 1px solid #e53935; background: white; color: #e53935;
            border-radius: 6px; padding: 0.3rem 0.8rem; font-size: 0.82rem;
            cursor: pointer;
        }
    """)

    def get_context(self, props):
        props['messages'] = chat.messages
        props['streaming_text'] = chat.streaming_text
        props['busy'] = chat.busy
        props['base_url'] = chat.base_url
        props['model_name'] = chat.model
        props['api_key'] = chat.api_key
        return props

    def send(self, text):
        chat.send(text)

    def stop(self):
        chat.stop()

    template = {
        h.div(Class='shell'): {
            ChatWindow(): {
                ChatWindow.S.header(): {
                    h.div(Class='settings'): {
                        h.label(): 'Endpoint',
                        h.input(Class='url-input', value={'base_url'},
                                onInput={'e => chat.base_url = e.target.value'}): None,
                        h.label(): 'Model',
                        h.input(value={'model_name'},
                                onInput={'e => chat.model = e.target.value'}): None,
                        h.label(): 'API key',
                        h.input(type='password', placeholder='(optional)', value={'api_key'},
                                onInput={'e => chat.api_key = e.target.value'}): None,
                        h.Template(If={'busy'}): {
                            h.button(Class='stop-btn', onClick={'self.stop'}): 'Stop',
                        },
                    },
                },
                MessageList(
                    messages={'messages'},
                    streaming_text={'streaming_text'},
                    streaming={'busy'},
                    empty_text='Say hello — replies stream in as markdown.',
                ): None,
                ChatInput(on_send={'self.send'}, disabled={'busy'},
                          placeholder='Message the model…'): None,
            }
        }
    }


mount(App, '#app')
