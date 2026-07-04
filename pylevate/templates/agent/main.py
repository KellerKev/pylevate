"""PyLevate agent template — a tool-calling agent with visible steps.

Ask something like "what is (17*23)+5?" and watch the model call the
calculator tool, get the result back, and answer. Each tool call renders as
an expandable card, Chainlit-style.
"""

from pylevate import Component, Store, action, css, h, mount
from pylevate.ai import AIClient
from pylevate.chat import ChatInput, ChatWindow, MessageList, ToolCallCard
from pylevate.signals import signal

from tools import calculator, fetch_url


class AgentStore(Store):
    messages = signal([])       # UI transcript: chat messages
    steps = signal([])          # tool activity: {name, args, result, status}
    streaming_text = signal(None)
    busy = signal(False)
    base_url = signal('http://localhost:11434/v1')
    model = signal('llama3.2')
    api_key = signal('')

    def on_rehydrate(self):
        self.busy = False
        self.streaming_text = None

    @action
    def push(self, msg):
        self.messages = [*self.messages, msg]

    @action
    def push_step(self, step):
        self.steps = [*self.steps, step]

    @action
    def finish_step(self, step_id, result, is_error):
        updated = []
        for s in self.steps:
            if s['id'] == step_id:
                updated.append({**s, 'result': result,
                                'status': 'error' if is_error else 'done'})
            else:
                updated.append(s)
        self.steps = updated

    @action
    def append_token(self, t):
        self.streaming_text = (self.streaming_text or '') + t

    def on_step(self, step):
        if step['type'] == 'tool_call':
            self.push_step({'id': step['id'], 'name': step['name'],
                            'args': step['args'], 'result': None, 'status': 'running'})
        elif step['type'] == 'tool_result':
            self.finish_step(step['id'], step['result'], step['is_error'])

    async def send(self, text):
        if self.busy:
            return
        self.push({'id': str(Date.now()), 'role': 'user', 'content': text})
        self.busy = True
        self.streaming_text = ''

        client = AIClient(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            system='You are a helpful assistant. Use the tools when they help; '
                   'show your final answer in plain language.',
        )
        try:
            result = await client.run_tools(
                self.messages,
                tools=[calculator, fetch_url],
                on_step=lambda s: self.on_step(s),
                on_token=lambda t: self.append_token(t),
            )
            self.push(result['final'])
        except Exception as e:
            self.push({'id': str(Date.now()), 'role': 'assistant',
                       'content': '**Error:** ' + str(e)})
        self.streaming_text = None
        self.busy = False


agent = AgentStore()


class App(Component):

    style = css("""
        .shell { height: 100vh; max-width: 900px; margin: 0 auto; display: flex; }
        .chat-pane { flex: 1.6; min-width: 0; }
        .steps-pane {
            flex: 1; min-width: 0; border-left: 1px solid #e0e0e0;
            background: #fff; overflow-y: auto; padding: 0.75rem;
            display: flex; flex-direction: column; gap: 0.5rem;
        }
        .steps-title { font-size: 0.8rem; color: #888; text-transform: uppercase;
                       letter-spacing: 0.05em; }
        .settings { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
        .settings label { font-size: 0.75rem; color: #888; }
        .settings input { border: 1px solid #d0d0d0; border-radius: 6px;
                          padding: 0.3rem 0.5rem; font-size: 0.82rem; }
    """)

    def get_context(self, props):
        props['messages'] = agent.messages
        props['steps'] = agent.steps
        props['streaming_text'] = agent.streaming_text
        props['busy'] = agent.busy
        props['base_url'] = agent.base_url
        props['model_name'] = agent.model
        props['api_key'] = agent.api_key
        return props

    def send(self, text):
        agent.send(text)

    template = {
        h.div(Class='shell'): {
            h.div(Class='chat-pane'): {
                ChatWindow(): {
                    ChatWindow.S.header(): {
                        h.div(Class='settings'): {
                            h.label(): 'Endpoint',
                            h.input(value={'base_url'},
                                    onInput={'e => agent.base_url = e.target.value'}): None,
                            h.label(): 'Model',
                            h.input(value={'model_name'},
                                    onInput={'e => agent.model = e.target.value'}): None,
                            h.label(): 'Key',
                            h.input(type='password', placeholder='(optional)', value={'api_key'},
                                    onInput={'e => agent.api_key = e.target.value'}): None,
                        },
                    },
                    MessageList(
                        messages={'messages'},
                        streaming_text={'streaming_text'},
                        streaming={'busy'},
                        empty_text='Try: what is (17*23)+5?',
                    ): None,
                    ChatInput(on_send={'self.send'}, disabled={'busy'},
                              placeholder='Ask something that needs a tool…'): None,
                }
            },
            h.div(Class='steps-pane'): {
                h.div(Class='steps-title'): 'Tool activity',
                h.Template(For='step in steps'): {
                    ToolCallCard(
                        key={'step["id"]'},
                        name={'step["name"]'},
                        args={'step["args"]'},
                        result={'step["result"]'},
                        status={'step["status"]'},
                        open={'step["status"] == "running"'},
                    ): None,
                },
            },
        }
    }


mount(App, '#app')
