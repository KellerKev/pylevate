from pylevate import Component, h, css, page

from components.nav import Navbar


@page(title='Settings — PyLevate Dashboard', route='/settings/:section')
class Settings(Component):

    style = css("""
        .page {
            max-width: 720px;
            margin: 2rem auto;
            padding: 0 1rem;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }
        .title { color: #333; margin-bottom: 1rem; }
        .section-name { color: #5c6bc0; }
    """)

    def get_context(self, props):
        # Route params (:section) arrive as props from the router.
        props['section_name'] = props.get('section') or 'general'
        return props

    template = {
        Navbar(): None,
        h.div(Class='page'): {
            h.h1(Class='title'): 'Settings',
            h.p(): {
                h.span(): 'Active section: ',
                h.span(Class='section-name'): '[[section_name]]',
            },
        }
    }
