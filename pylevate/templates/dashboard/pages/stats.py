from pylevate import Component, h, css, page

from components.nav import Navbar
from stores.counter import counter


@page(title='Stats — PyLevate Dashboard', route='/stats')
class Stats(Component):

    style = css("""
        .page {
            max-width: 720px;
            margin: 2rem auto;
            padding: 0 1rem;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }
        .title { color: #333; margin-bottom: 1.5rem; }
        .tiles { display: flex; gap: 1rem; }
        .tile {
            flex: 1;
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 1.25rem;
        }
        .tile-label { color: #888; font-size: 0.85rem; margin-bottom: 0.25rem; }
        .tile-value { color: #333; font-size: 1.75rem; font-weight: bold; }
    """)

    def get_context(self, props):
        props['count'] = counter.count
        props['doubled'] = counter.count * 2
        return props

    template = {
        Navbar(): None,
        h.div(Class='page'): {
            h.h1(Class='title'): 'Stats',
            h.div(Class='tiles'): {
                h.div(Class='tile'): {
                    h.div(Class='tile-label'): 'Clicks',
                    h.div(Class='tile-value'): '[[count]]',
                },
                h.div(Class='tile'): {
                    h.div(Class='tile-label'): 'Doubled',
                    h.div(Class='tile-value'): '[[doubled]]',
                },
            },
        }
    }
