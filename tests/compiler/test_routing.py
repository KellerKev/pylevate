"""Golden tests pinning the compiler output shapes the routing runtime relies on.

The JS runtime (js/pylevate-runtime.js) implements App/Router/page against
exactly these shapes; if a codegen heuristic changes them, these tests fail
before the runtime silently breaks.
"""

from pylevate.compiler.py2js import compile_source


def _js(source: str) -> str:
    result = compile_source(source, "test.py", "app")
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js


class TestRoutingCodegen:
    def test_runtime_import(self):
        js = _js("from pylevate import App, Router, page")
        assert "import { App, Router, page } from 'pylevate-runtime'" in js

    def test_app_with_router_shape(self):
        js = _js(
            "from pylevate import App, Router\n"
            "from pages.home import Home\n"
            "from pages.profile import Profile\n"
            "app = App(router=Router([('/', Home), ('/profile/:id', Profile)]))\n"
        )
        assert "new App({router: new Router([['/', Home], ['/profile/:id', Profile]])})" in js

    def test_app_mount_call(self):
        js = _js(
            "from pylevate import App, Router\n"
            "app = App(router=Router([]))\n"
            "app.mount('#app')\n"
        )
        assert "app.mount('#app');" in js

    def test_theme_kwarg_in_options_object(self):
        js = _js(
            "from pylevate import App, Router\n"
            "app = App(router=Router([]), theme='styles/global.css')\n"
        )
        assert "theme: 'styles/global.css'" in js

    def test_page_decorator_shape(self):
        js = _js(
            "from pylevate import Component, h, page\n"
            "\n"
            "@page(title='Profile', route='/profile/:id')\n"
            "class Profile(Component):\n"
            "    template = {\n"
            "        h.div(): 'hi',\n"
            "    }\n"
        )
        assert "class Profile extends Component" in js
        assert "Profile = page({title: 'Profile', route: '/profile/:id'})(Profile);" in js
