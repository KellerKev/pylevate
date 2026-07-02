"""Platformer game scene — runs in Phaser canvas underneath the HUD."""

import pylevate.game as pg
from pylevate.events import game_events

pg.init()
screen = pg.display.set_mode((800, 600))
pg.display.set_caption('Platformer')

score = 0
lives = 3


class Player(pg.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pg.image.load('assets/player.png')
        self.rect = self.image.get_rect()
        self.rect.center = (100, 400)
        self.speed = 5
        self.jump_power = -12
        self.vel_y = 0
        self.on_ground = False

    def update(self):
        keys = pg.key.get_pressed()
        if keys[pg.K_LEFT]:
            self.rect.x -= self.speed
        if keys[pg.K_RIGHT]:
            self.rect.x += self.speed
        if keys[pg.K_UP] and self.on_ground:
            self.vel_y = self.jump_power
            self.on_ground = False

        # Gravity
        self.vel_y += 1
        self.rect.y += self.vel_y

        # Floor
        if self.rect.bottom >= 550:
            self.rect.bottom = 550
            self.vel_y = 0
            self.on_ground = True


class Coin(pg.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pg.image.load('assets/coin.png')
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)


# Setup
all_sprites = pg.sprite.Group()
coins = pg.sprite.Group()

player = Player()
all_sprites.add(player)

# Place coins
for i in range(5):
    c = Coin(150 + i * 120, 350)
    all_sprites.add(c)
    coins.add(c)

clock = pg.time.Clock()
running = True

while running:
    for event in pg.event.get():
        if event.type == pg.QUIT:
            running = False

    all_sprites.update()

    # Coin collection
    collected = pg.sprite.spritecollide(player, coins, True)
    if len(collected) > 0:
        score += len(collected) * 100
        game_events.emit('score_change', score)

    screen.fill((40, 40, 80))
    all_sprites.draw(screen)
    pg.display.flip()
    clock.tick(60)
