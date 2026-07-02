"""Phase 7 tests — Game loop hoister."""

from pylevate.compiler.loop_hoister import hoist_game_loop


class TestAssetHoisting:
    def test_image_load_detected(self):
        js = """
import * as pg from 'pylevate-game-runtime';
let screen = pg.display.set_mode([800, 600]);
let img = pg.image.load('assets/player.png');
let running = true;
while (running) {
  pg.display.flip();
}
"""
        result = hoist_game_loop(js, "test")
        assert "scene.load.image('player', 'assets/player.png')" in result

    def test_sound_load_detected(self):
        js = """
import * as pg from 'pylevate-game-runtime';
let snd = pg.mixer.Sound('assets/shoot.wav');
while (true) {}
"""
        result = hoist_game_loop(js, "test")
        assert "scene.load.audio('shoot', 'assets/shoot.wav')" in result


class TestSetupHoisting:
    def test_setup_code_in_create(self):
        js = """
import * as pg from 'pylevate-game-runtime';
pg.display.set_mode([800, 600]);
let player = new Player();
let all_sprites = pg.sprite.Group();
all_sprites.add(player);
while (true) {}
"""
        result = hoist_game_loop(js, "test")
        assert "new Player()" in result
        assert "pg.sprite.Group()" in result
        assert "_create" in result

    def test_display_dimensions_extracted(self):
        js = """
import * as pg from 'pylevate-game-runtime';
pg.display.set_mode([640, 480]);
while (true) {}
"""
        result = hoist_game_loop(js, "test")
        assert "width: 640" in result
        assert "height: 480" in result


class TestLoopExtraction:
    def test_while_body_in_update(self):
        js = """
import * as pg from 'pylevate-game-runtime';
while (running) {
  all_sprites.update();
  pg.display.flip();
}
"""
        result = hoist_game_loop(js, "test")
        assert "all_sprites.update()" in result
        assert "_update" in result

    def test_noop_elided(self):
        js = """
import * as pg from 'pylevate-game-runtime';
while (running) {
  all_sprites.update();
  screen.fill([0, 0, 0]);
  all_sprites.draw(screen);
  pg.display.flip();
  clock.tick(60);
}
"""
        result = hoist_game_loop(js, "test")
        # These should be elided
        assert "display.flip()" not in result
        assert ".draw(screen)" not in result
        # But update should remain
        assert "all_sprites.update()" in result


class TestEventLoopElision:
    def test_event_loop_removed(self):
        js = """
import * as pg from 'pylevate-game-runtime';
while (running) {
  for (let event of pg.event.get()) {
    if (event.type === pg.QUIT) {
      running = false;
    }
  }
  all_sprites.update();
}
"""
        result = hoist_game_loop(js, "test")
        # Event loop boilerplate should not appear in update
        assert "pg.event.get" not in result
        assert "QUIT" not in result
        # But update() should have the sprite update
        assert "all_sprites.update()" in result


class TestClassPreservation:
    def test_sprite_classes_preserved(self):
        js = """
import * as pg from 'pylevate-game-runtime';
export class Player extends pg.Sprite {
  constructor() {
    super();
    this.speed = 5;
  }
  update() {
    this.rect.x += this.speed;
  }
}
while (true) {}
"""
        result = hoist_game_loop(js, "test")
        assert "class Player extends pg.Sprite" in result
        assert "this.speed = 5" in result
        assert "update()" in result


class TestOutputStructure:
    def test_creates_game_call(self):
        js = """
import * as pg from 'pylevate-game-runtime';
pg.display.set_mode([800, 600]);
while (true) {}
"""
        result = hoist_game_loop(js, "test")
        assert "createGame({" in result
        assert "preloadFn:" in result
        assert "createFn:" in result
        assert "updateFn:" in result

    def test_bg_color_extracted(self):
        js = """
import * as pg from 'pylevate-game-runtime';
while (running) {
  screen.fill([0, 0, 30]);
}
"""
        result = hoist_game_loop(js, "test")
        assert "0x00001e" in result  # rgb(0, 0, 30) as hex
