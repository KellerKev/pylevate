"""Hybrid mode — Platformer game with Preact HUD overlay."""

from pylevate import Component, h, state, css, mount
from pylevate.events import game_events


class HUD(Component):
    score = state(0)
    lives = state(3)

    style = css("""
        .hud {
            position: fixed; top: 0; left: 0; right: 0;
            display: flex; justify-content: space-between;
            padding: 1rem 2rem;
            font-family: 'Press Start 2P', monospace, system-ui;
            font-size: 1.2rem; color: white;
            pointer-events: none; z-index: 10;
        }
        .score { text-shadow: 2px 2px 0 #000; }
        .lives { text-shadow: 2px 2px 0 #000; }
    """)

    def on_mount(self):
        game_events.on('score_change', self._on_score)
        game_events.on('life_lost', self._on_life_lost)

    def _on_score(self, val):
        self.score = val

    def _on_life_lost(self):
        self.lives = self.lives - 1

    template = {
        h.div(Class='hud'): {
            h.span(Class='score'): 'Score: [[self.score]]',
            h.span(Class='lives'): 'Lives: [[self.lives]]',
        }
    }


# Mount UI overlay
mount(HUD, '#ui-layer')
