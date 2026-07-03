from pylevate import Component, h, css


class Navbar(Component):

    style = css("""
        .nav {
            display: flex;
            gap: 1.5rem;
            align-items: center;
            padding: 1rem 2rem;
            background: #5c6bc0;
        }
        .brand {
            color: white;
            font-weight: bold;
            font-size: 1.1rem;
            margin-right: 1rem;
        }
        .link {
            color: rgba(255, 255, 255, 0.85);
            text-decoration: none;
        }
        .link:hover {
            color: white;
        }
    """)

    template = {
        h.nav(Class='nav'): {
            h.span(Class='brand'): 'PyLevate',
            h.a(Class='link', href='/'): 'Home',
            h.a(Class='link', href='/stats'): 'Stats',
            h.a(Class='link', href='/settings/profile'): 'Settings',
        }
    }
