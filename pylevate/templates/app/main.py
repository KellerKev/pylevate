from pylevate import Component, h, state, css, mount


class App(Component):

    count = state(0)

    style = css("""
        .app {
            max-width: 600px;
            margin: 2rem auto;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            text-align: center;
        }
        .title {
            color: #5c6bc0;
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }
        .subtitle {
            color: #888;
            font-size: 1rem;
            margin-bottom: 2rem;
        }
        .counter {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1rem;
            margin: 2rem 0;
        }
        .btn {
            background: #5c6bc0;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0.5rem 1.5rem;
            font-size: 1.1rem;
            cursor: pointer;
            transition: background 0.2s;
        }
        .btn:hover {
            background: #3f51b5;
        }
        .count {
            font-size: 2rem;
            font-weight: bold;
            min-width: 3rem;
        }
    """)

    def increment(self):
        self.count += 1

    def decrement(self):
        self.count -= 1

    template = {
        h.div(Class='app'): {
            h.h1(Class='title'): 'Hello from PyLevate',
            h.p(Class='subtitle'): 'Write Python. Ship web apps.',
            h.div(Class='counter'): {
                h.button(Class='btn', onClick={'self.decrement'}): '-',
                h.span(Class='count'): '[[self.count]]',
                h.button(Class='btn', onClick={'self.increment'}): '+',
            },
        }
    }


mount(App, '#app')
