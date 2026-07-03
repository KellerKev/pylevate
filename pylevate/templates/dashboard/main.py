from pylevate import App, Router

from pages.home import Home
from pages.stats import Stats
from pages.settings import Settings

app = App(router=Router([
    ('/', Home),
    ('/stats', Stats),
    ('/settings/:section', Settings),
]))
app.mount('#app')
