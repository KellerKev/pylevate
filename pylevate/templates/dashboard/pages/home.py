from pylevate import Component, h, css, page

from components.nav import Navbar
from stores.counter import counter


@page(title='Home — PyLevate Dashboard', route='/')
class Home(Component):

    style = css("""
        .page {
            max-width: 720px;
            margin: 2rem auto;
            padding: 0 1rem;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }
        .title { color: #333; margin-bottom: 0.5rem; }
        .subtitle { color: #888; margin-bottom: 2rem; }
        .btn {
            background: #5c6bc0;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0.5rem 1.5rem;
            font-size: 1rem;
            cursor: pointer;
        }
        .btn:hover { background: #3f51b5; }
    """)

    def get_context(self, props):
        props['count'] = counter.count
        return props

    def bump(self):
        counter.increment()

    template = {
        Navbar(): None,
        h.div(Class='page'): {
            h.h1(Class='title'): 'Welcome',
            h.p(Class='subtitle'): 'A routed PyLevate app. Edit a page and save — you land right back here.',
            h.p(): 'Store clicks: [[count]]',
            h.button(Class='btn', onClick={'self.bump'}): 'Click me',
        }
    }
