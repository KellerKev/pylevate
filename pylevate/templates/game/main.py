"""Space Shooter — PyLevate game demo.

This file runs with real pygame locally:
    pip install pygame && python main.py

And compiles to Phaser for web/mobile:
    pylevate dev
"""

import pylevate.game as pg
import random

# Initialize
pg.init()
screen = pg.display.set_mode((800, 600))
pg.display.set_caption('Space Shooter')

# Score
score = 0


class Player(pg.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pg.image.load('assets/player.png')
        self.rect = self.image.get_rect()
        self.rect.center = (400, 550)
        self.speed = 6

    def update(self):
        keys = pg.key.get_pressed()
        if keys[pg.K_LEFT] and self.rect.left > 0:
            self.rect.x -= self.speed
        if keys[pg.K_RIGHT] and self.rect.right < 800:
            self.rect.x += self.speed

    def shoot(self):
        bullet = Bullet(self.rect.centerx, self.rect.top)
        all_sprites.add(bullet)
        bullets.add(bullet)


class Enemy(pg.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pg.image.load('assets/enemy.png')
        self.rect = self.image.get_rect()
        self.rect.x = random.randrange(0, 750)
        self.rect.y = random.randrange(-150, -40)
        self.speedy = random.randrange(2, 6)

    def update(self):
        self.rect.y += self.speedy
        if self.rect.top > 600:
            self.rect.x = random.randrange(0, 750)
            self.rect.y = random.randrange(-150, -40)


class Bullet(pg.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pg.image.load('assets/bullet.png')
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)

    def update(self):
        self.rect.y -= 12
        if self.rect.bottom < 0:
            self.kill()


# Create groups
all_sprites = pg.sprite.Group()
bullets = pg.sprite.Group()
enemies = pg.sprite.Group()

# Create player
player = Player()
all_sprites.add(player)

# Create enemies
for i in range(8):
    e = Enemy()
    all_sprites.add(e)
    enemies.add(e)

# HUD font
font = pg.font.Font(None, 36)

# Game loop
clock = pg.time.Clock()
running = True

while running:
    for event in pg.event.get():
        if event.type == pg.QUIT:
            running = False
        if event.type == pg.KEYDOWN:
            if event.key == pg.K_SPACE:
                player.shoot()

    all_sprites.update()

    # Bullet-enemy collisions
    hits = pg.sprite.groupcollide(bullets, enemies, True, True)
    for bullet, enemy_list in hits.items():
        score += len(enemy_list) * 10
        for e in enemy_list:
            new_enemy = Enemy()
            all_sprites.add(new_enemy)
            enemies.add(new_enemy)

    # Player-enemy collisions
    player_hits = pg.sprite.spritecollide(player, enemies, False)

    # Draw
    screen.fill((0, 0, 30))
    all_sprites.draw(screen)

    # HUD
    score_text = font.render(f'Score: {score}', True, (255, 255, 255))
    screen.blit(score_text, (10, 10))

    pg.display.flip()
    clock.tick(60)
