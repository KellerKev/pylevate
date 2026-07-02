/**
 * PyLevate Game Runtime — pygame-compatible API shim on Phaser 3.
 *
 * This module provides a pygame-like API that runs in the browser using
 * Phaser 3 as the rendering and physics engine. Compiled game code imports
 * from this module and never touches Phaser directly.
 *
 * Phaser must be loaded from CDN before this module runs (window.Phaser).
 */

// ---------------------------------------------------------------------------
// Phaser reference
// ---------------------------------------------------------------------------
const Phaser = window.Phaser;

// ---------------------------------------------------------------------------
// Internal state shared across the shim
// ---------------------------------------------------------------------------

/** The active Phaser scene, set when PygameScene boots. */
let _scene = null;

/** The event queue — populated by Phaser input callbacks, drained by pg.event.get(). */
let _eventQueue = [];

/** Map of currently-pressed key constants to booleans. */
let _keysDown = {};

/** Current mouse position. */
let _mousePos = { x: 0, y: 0 };
let _mouseButtons = [false, false, false];  // [left, middle, right]

/** Screen dimensions (set by display.set_mode). */
let _screenWidth = 800;
let _screenHeight = 600;

/** Registry of image paths that need preloading. */
const _preloadPaths = new Set();

/** Registry of audio paths that need preloading. */
const _audioPreloadPaths = new Set();

/** All active sprite groups, so PygameScene can call draw on them. */
const _allGroups = new Set();

// ---------------------------------------------------------------------------
// Constants — pygame event types
// ---------------------------------------------------------------------------

export const QUIT = 256;
export const KEYDOWN = 768;
export const KEYUP = 769;
export const MOUSEBUTTONDOWN = 1025;
export const MOUSEBUTTONUP = 1026;
export const MOUSEMOTION = 1024;

// ---------------------------------------------------------------------------
// Constants — pygame key codes
// ---------------------------------------------------------------------------

export const K_LEFT = 276;
export const K_RIGHT = 275;
export const K_UP = 273;
export const K_DOWN = 274;
export const K_SPACE = 32;
export const K_RETURN = 13;
export const K_ESCAPE = 27;

// Letter keys K_a..K_z  (pygame uses ASCII-ish codes: a=97..z=122)
export const K_a = 97;
export const K_b = 98;
export const K_c = 99;
export const K_d = 100;
export const K_e = 101;
export const K_f = 102;
export const K_g = 103;
export const K_h = 104;
export const K_i = 105;
export const K_j = 106;
export const K_k = 107;
export const K_l = 108;
export const K_m = 109;
export const K_n = 110;
export const K_o = 111;
export const K_p = 112;
export const K_q = 113;
export const K_r = 114;
export const K_s = 115;
export const K_t = 116;
export const K_u = 117;
export const K_v = 118;
export const K_w = 119;
export const K_x = 120;
export const K_y = 121;
export const K_z = 122;

// Number keys K_0..K_9  (pygame: 48..57)
export const K_0 = 48;
export const K_1 = 49;
export const K_2 = 50;
export const K_3 = 51;
export const K_4 = 52;
export const K_5 = 53;
export const K_6 = 54;
export const K_7 = 55;
export const K_8 = 56;
export const K_9 = 57;

// ---------------------------------------------------------------------------
// Internal: map Phaser key codes to our pygame constants
// ---------------------------------------------------------------------------

const _phaserToKey = {};

function _initKeyMap() {
  if (!Phaser) return;
  const K = Phaser.Input.Keyboard.KeyCodes;
  _phaserToKey[K.LEFT] = K_LEFT;
  _phaserToKey[K.RIGHT] = K_RIGHT;
  _phaserToKey[K.UP] = K_UP;
  _phaserToKey[K.DOWN] = K_DOWN;
  _phaserToKey[K.SPACE] = K_SPACE;
  _phaserToKey[K.ENTER] = K_RETURN;
  _phaserToKey[K.ESC] = K_ESCAPE;

  // Letters
  for (let i = 0; i < 26; i++) {
    const letter = String.fromCharCode(65 + i); // 'A'..'Z'
    if (K[letter] !== undefined) {
      _phaserToKey[K[letter]] = 97 + i; // K_a..K_z
    }
  }

  // Digits
  for (let i = 0; i <= 9; i++) {
    const digit = `ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE`.split(' ')[i];
    if (K[digit] !== undefined) {
      _phaserToKey[K[digit]] = 48 + i;
    }
  }
}

/** Convert a Phaser keyCode to our pygame constant, or return the raw code. */
function _translateKey(phaserKeyCode) {
  return _phaserToKey[phaserKeyCode] ?? phaserKeyCode;
}

// ---------------------------------------------------------------------------
// Rect class — pygame.Rect
// ---------------------------------------------------------------------------

export class Rect {
  constructor(x = 0, y = 0, width = 0, height = 0) {
    this._x = x;
    this._y = y;
    this._w = width;
    this._h = height;
  }

  // --- Basic properties ---
  get x() { return this._x; }
  set x(v) { this._x = v; }

  get y() { return this._y; }
  set y(v) { this._y = v; }

  get width() { return this._w; }
  set width(v) { this._w = v; }

  get height() { return this._h; }
  set height(v) { this._h = v; }

  get w() { return this._w; }
  set w(v) { this._w = v; }

  get h() { return this._h; }
  set h(v) { this._h = v; }

  // --- Derived edge properties ---
  get left() { return this._x; }
  set left(v) { this._x = v; }

  get top() { return this._y; }
  set top(v) { this._y = v; }

  get right() { return this._x + this._w; }
  set right(v) { this._x = v - this._w; }

  get bottom() { return this._y + this._h; }
  set bottom(v) { this._y = v - this._h; }

  get centerx() { return this._x + this._w / 2; }
  set centerx(v) { this._x = v - this._w / 2; }

  get centery() { return this._y + this._h / 2; }
  set centery(v) { this._y = v - this._h / 2; }

  get center() { return [this.centerx, this.centery]; }
  set center(v) {
    this.centerx = v[0];
    this.centery = v[1];
  }

  get topleft() { return [this._x, this._y]; }
  set topleft(v) { this._x = v[0]; this._y = v[1]; }

  get topright() { return [this.right, this._y]; }
  set topright(v) { this.right = v[0]; this._y = v[1]; }

  get bottomleft() { return [this._x, this.bottom]; }
  set bottomleft(v) { this._x = v[0]; this.bottom = v[1]; }

  get bottomright() { return [this.right, this.bottom]; }
  set bottomright(v) { this.right = v[0]; this.bottom = v[1]; }

  get midtop() { return [this.centerx, this._y]; }
  get midbottom() { return [this.centerx, this.bottom]; }
  get midleft() { return [this._x, this.centery]; }
  get midright() { return [this.right, this.centery]; }

  get size() { return [this._w, this._h]; }

  /** AABB collision check. */
  colliderect(other) {
    return (
      this._x < other.x + other.width &&
      this._x + this._w > other.x &&
      this._y < other.y + other.height &&
      this._y + this._h > other.y
    );
  }

  /** Return a copy of this rect. */
  copy() {
    return new Rect(this._x, this._y, this._w, this._h);
  }

  /** Move the rect by (dx, dy) and return a new Rect. */
  move(dx, dy) {
    return new Rect(this._x + dx, this._y + dy, this._w, this._h);
  }

  /** Move the rect in-place. */
  move_ip(dx, dy) {
    this._x += dx;
    this._y += dy;
  }

  /** Clamp this rect inside another. */
  clamp_ip(other) {
    if (this._x < other.x) this._x = other.x;
    if (this._y < other.y) this._y = other.y;
    if (this.right > other.right) this.right = other.right;
    if (this.bottom > other.bottom) this.bottom = other.bottom;
  }

  /** Check if a point (px, py) is inside this rect. */
  collidepoint(px, py) {
    // Accept both collidepoint(x, y) and collidepoint([x, y])
    if (Array.isArray(px)) { py = px[1]; px = px[0]; }
    return px >= this._x && px < this._x + this._w &&
           py >= this._y && py < this._y + this._h;
  }
}

// ---------------------------------------------------------------------------
// Surface proxy — returned by display.set_mode() and image.load()
// ---------------------------------------------------------------------------

class Surface {
  constructor(width, height, imagePath = null) {
    this._width = width;
    this._height = height;
    this._imagePath = imagePath;
    this._textContent = null;  // for font-rendered surfaces
    this._textColor = null;
    this._fontSize = 16;
    this._fontName = null;
  }

  get_rect() {
    return new Rect(0, 0, this._width, this._height);
  }

  get_width() { return this._width; }
  get_height() { return this._height; }
  get_size() { return [this._width, this._height]; }

  /** Fill — on the screen surface, set the camera background so a per-frame
   *  `screen.fill(...)` actually clears the canvas. No-op for image surfaces. */
  fill(color) {
    if (this === _screenSurface && _scene && _scene.cameras && _scene.cameras.main) {
      _scene.cameras.main.setBackgroundColor(_colorToHex(color));
    }
  }

  /** Blit — draw one surface onto this one. Used for screen.blit(). */
  blit(source, dest) {
    // This gets intercepted by the scene's render loop.
    // We store the blit request so the scene can process it.
    if (_scene && _scene._blitQueue) {
      const dx = Array.isArray(dest) ? dest[0] : (dest.x ?? 0);
      const dy = Array.isArray(dest) ? dest[1] : (dest.y ?? 0);
      _scene._blitQueue.push({ source, x: dx, y: dy });
    }
  }
}

// ---------------------------------------------------------------------------
// pg.init()
// ---------------------------------------------------------------------------

export function init() {
  // No-op in browser — Phaser initializes via game config.
  _initKeyMap();
}

/** pg.quit() — Phaser owns the lifecycle, so this is a harmless no-op (it used
 *  to be undefined → "(void 0) is not a function" at runtime). */
export function quit() {}

// ---------------------------------------------------------------------------
// pg.display
// ---------------------------------------------------------------------------

let _screenSurface = null;

export const display = {
  /** Set the display mode. Returns a Surface proxy representing the screen. */
  set_mode(size) {
    _screenWidth = size[0];
    _screenHeight = size[1];
    _screenSurface = new Surface(_screenWidth, _screenHeight);
    return _screenSurface;
  },

  /** Set the window/tab title. */
  set_caption(title) {
    document.title = title;
  },

  /** Flip — no-op, Phaser manages rendering. */
  flip() {},

  /** Update — no-op alias for flip. */
  update() {},
};

// ---------------------------------------------------------------------------
// pg.time
// ---------------------------------------------------------------------------

export const time = {
  /** Return a Clock object. */
  Clock() {
    return {
      /** tick — no-op, Phaser manages the frame rate. Returns delta ms. */
      tick(fps) {
        return _scene ? _scene.game.loop.delta : 16;
      },

      /** get_ticks — return ms since game started. */
      get_ticks() {
        return _scene ? _scene.time.now : Date.now();
      },
    };
  },

  /** Return millisecond timestamp. */
  get_ticks() {
    return _scene ? _scene.time.now : Date.now();
  },

  /** Delay — returns a promise (non-blocking in browser). */
  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  },
};

// ---------------------------------------------------------------------------
// pg.event
// ---------------------------------------------------------------------------

export const event = {
  /** Return and drain the event queue. */
  get() {
    const events = _eventQueue.slice();
    _eventQueue.length = 0;
    return events;
  },

  /** Peek at the queue without draining it. */
  peek() {
    return _eventQueue.length > 0;
  },

  /** Pump — no-op, events are pushed by Phaser callbacks. */
  pump() {},
};

// ---------------------------------------------------------------------------
// pg.key
// ---------------------------------------------------------------------------

export const key = {
  /**
   * Return a dict-like object mapping key constants to booleans.
   * Uses a Proxy so any key constant lookup works even if not explicitly tracked.
   */
  get_pressed() {
    return new Proxy(_keysDown, {
      get(target, prop) {
        const k = typeof prop === 'string' ? parseInt(prop, 10) : prop;
        return !!target[k];
      },
    });
  },
};

// ---------------------------------------------------------------------------
// pg.mouse
// ---------------------------------------------------------------------------

export const mouse = {
  /** Return current mouse position as [x, y]. */
  get_pos() {
    return [_mousePos.x, _mousePos.y];
  },

  /** Return mouse button state [left, middle, right]. */
  get_pressed() {
    return [..._mouseButtons];
  },
};

// ---------------------------------------------------------------------------
// pg.image
// ---------------------------------------------------------------------------

/** Derive a Phaser-friendly asset key from a file path. */
function _assetKey(path) {
  return path.replace(/[^a-zA-Z0-9_-]/g, '_');
}

export const image = {
  /**
   * Load an image from a path. Returns a Surface-like object.
   * The path is registered for preloading — the actual Phaser texture
   * is loaded during the scene's preload phase.
   */
  load(path) {
    _preloadPaths.add(path);
    const assetKey = _assetKey(path);
    const surf = new Surface(0, 0, path);
    surf._assetKey = assetKey;

    // Once the scene is live and the texture is loaded, update dimensions.
    Object.defineProperty(surf, '_width', {
      get() {
        if (_scene && _scene.textures.exists(assetKey)) {
          return _scene.textures.get(assetKey).getSourceImage().width;
        }
        return 32; // fallback
      },
      configurable: true,
    });
    Object.defineProperty(surf, '_height', {
      get() {
        if (_scene && _scene.textures.exists(assetKey)) {
          return _scene.textures.get(assetKey).getSourceImage().height;
        }
        return 32; // fallback
      },
      configurable: true,
    });

    return surf;
  },
};

// ---------------------------------------------------------------------------
// pg.transform — scale / rotate / flip
// Returns a derived Surface carrying transform state; the Sprite render path
// (_syncPosition) applies it to the Phaser object each frame.
// ---------------------------------------------------------------------------

function _deriveSurface(surf) {
  const s = new Surface(surf._width, surf._height, surf._imagePath);
  s._assetKey = surf._assetKey;
  s._textContent = surf._textContent;
  s._textColor = surf._textColor;
  s._fontName = surf._fontName;
  s._fontSize = surf._fontSize;
  s._scaleW = surf._scaleW; s._scaleH = surf._scaleH;
  s._angle = surf._angle; s._flipX = surf._flipX; s._flipY = surf._flipY;
  const dw = Object.getOwnPropertyDescriptor(surf, '_width');
  const dh = Object.getOwnPropertyDescriptor(surf, '_height');
  if (dw && dw.get) Object.defineProperty(s, '_width', dw);
  if (dh && dh.get) Object.defineProperty(s, '_height', dh);
  return s;
}

export const transform = {
  /** Scale to an absolute (width, height), like pygame.transform.scale. */
  scale(surf, size) {
    const s = _deriveSurface(surf);
    s._scaleW = size[0];
    s._scaleH = size[1];
    return s;
  },
  /** Rotate by degrees (pygame is counter-clockwise; Phaser angle is clockwise). */
  rotate(surf, degrees) {
    const s = _deriveSurface(surf);
    s._angle = -degrees;
    return s;
  },
  /** Flip horizontally/vertically. */
  flip(surf, flipX, flipY) {
    const s = _deriveSurface(surf);
    s._flipX = !!flipX;
    s._flipY = !!flipY;
    return s;
  },
};

// ---------------------------------------------------------------------------
// pg.mixer — Sound and music
// ---------------------------------------------------------------------------

export const mixer = {
  /** Initialize the mixer (no-op). */
  init() {},

  /** Create a Sound object. */
  Sound(path) {
    _audioPreloadPaths.add(path);
    const assetKey = _assetKey(path);

    return {
      _key: assetKey,
      _path: path,

      play() {
        if (_scene && _scene.sound) {
          _scene.sound.play(assetKey);
        }
      },

      stop() {
        if (_scene && _scene.sound) {
          _scene.sound.stopByKey(assetKey);
        }
      },

      set_volume(vol) {
        // Volume is 0.0..1.0
        if (_scene && _scene.sound) {
          const snd = _scene.sound.get(assetKey);
          if (snd) snd.volume = vol;
        }
      },
    };
  },

  /** Music sub-module for background music. */
  music: {
    _currentKey: null,
    _currentPath: null,

    load(path) {
      _audioPreloadPaths.add(path);
      mixer.music._currentPath = path;
      mixer.music._currentKey = _assetKey(path);
    },

    play(loops = 0) {
      if (_scene && _scene.sound && mixer.music._currentKey) {
        _scene.sound.play(mixer.music._currentKey, {
          loop: loops === -1 || loops > 0,
        });
      }
    },

    stop() {
      if (_scene && _scene.sound && mixer.music._currentKey) {
        _scene.sound.stopByKey(mixer.music._currentKey);
      }
    },

    set_volume(vol) {
      if (_scene && _scene.sound && mixer.music._currentKey) {
        const snd = _scene.sound.get(mixer.music._currentKey);
        if (snd) snd.volume = vol;
      }
    },

    pause() {
      if (_scene && _scene.sound && mixer.music._currentKey) {
        _scene.sound.pauseByKey(mixer.music._currentKey);
      }
    },

    unpause() {
      if (_scene && _scene.sound && mixer.music._currentKey) {
        _scene.sound.resumeByKey(mixer.music._currentKey);
      }
    },
  },
};

// ---------------------------------------------------------------------------
// pg.font — Font and text rendering
// ---------------------------------------------------------------------------

export const font = {
  /** Initialize the font module (no-op). */
  init() {},

  /**
   * Create a Font object for rendering text.
   * @param {string|null} name  Font family name (null = default sans-serif)
   * @param {number} size       Font size in pixels
   */
  Font(name, size) {
    const fontFamily = name || 'sans-serif';
    const fontSize = size || 16;

    return {
      _fontFamily: fontFamily,
      _fontSize: fontSize,

      /**
       * Render text to a Surface-like object.
       * The actual rendering happens in the Phaser scene via Text game objects.
       */
      render(text, antialias, color) {
        const surf = new Surface(0, 0);
        surf._textContent = text;
        surf._textColor = _colorToCSS(color);
        surf._fontSize = fontSize;
        surf._fontName = fontFamily;

        // Estimate dimensions (will be refined when drawn)
        surf._width = text.length * fontSize * 0.6;
        surf._height = fontSize * 1.2;
        return surf;
      },

      /** Return the pixel size of rendered text. */
      size(text) {
        return [text.length * fontSize * 0.6, fontSize * 1.2];
      },
    };
  },

  /** System font constructor — maps to Font with the given name. */
  SysFont(name, size) {
    return font.Font(name, size);
  },
};

// ---------------------------------------------------------------------------
// pg.draw — Primitive drawing
// ---------------------------------------------------------------------------

export const draw = {
  /**
   * Draw a filled or outlined rectangle.
   * color: [r, g, b] or CSS string
   * rect_or_tuple: Rect instance, [x, y, w, h], or {x, y, width, height}
   */
  rect(surface, color, rect_or_tuple, width = 0) {
    if (!_scene) return;
    const r = _normalizeRect(rect_or_tuple);
    const hex = _colorToHex(color);
    const gfx = _scene._getGraphics();
    if (width === 0) {
      gfx.fillStyle(hex, 1);
      gfx.fillRect(r.x, r.y, r.width, r.height);
    } else {
      gfx.lineStyle(width, hex, 1);
      gfx.strokeRect(r.x, r.y, r.width, r.height);
    }
  },

  /** Draw a filled or outlined circle. */
  circle(surface, color, center, radius, width = 0) {
    if (!_scene) return;
    const cx = Array.isArray(center) ? center[0] : center.x;
    const cy = Array.isArray(center) ? center[1] : center.y;
    const hex = _colorToHex(color);
    const gfx = _scene._getGraphics();
    if (width === 0) {
      gfx.fillStyle(hex, 1);
      gfx.fillCircle(cx, cy, radius);
    } else {
      gfx.lineStyle(width, hex, 1);
      gfx.strokeCircle(cx, cy, radius);
    }
  },

  /** Draw a line between two points. */
  line(surface, color, start, end, width = 1) {
    if (!_scene) return;
    const sx = Array.isArray(start) ? start[0] : start.x;
    const sy = Array.isArray(start) ? start[1] : start.y;
    const ex = Array.isArray(end) ? end[0] : end.x;
    const ey = Array.isArray(end) ? end[1] : end.y;
    const hex = _colorToHex(color);
    const gfx = _scene._getGraphics();
    gfx.lineStyle(width, hex, 1);
    gfx.lineBetween(sx, sy, ex, ey);
  },

  /** Draw an ellipse. */
  ellipse(surface, color, rect_or_tuple, width = 0) {
    if (!_scene) return;
    const r = _normalizeRect(rect_or_tuple);
    const hex = _colorToHex(color);
    const gfx = _scene._getGraphics();
    const cx = r.x + r.width / 2;
    const cy = r.y + r.height / 2;
    if (width === 0) {
      gfx.fillStyle(hex, 1);
      gfx.fillEllipse(cx, cy, r.width, r.height);
    } else {
      gfx.lineStyle(width, hex, 1);
      gfx.strokeEllipse(cx, cy, r.width, r.height);
    }
  },
};

// ---------------------------------------------------------------------------
// Sprite class — pygame.sprite.Sprite
// ---------------------------------------------------------------------------

export class Sprite {
  constructor() {
    /** The image surface — set by subclass via pg.image.load(). */
    this.image = null;

    /** The bounding rect — updated from the Phaser game object. */
    this.rect = new Rect(0, 0, 0, 0);

    /** Phaser game object backing this sprite (created on first draw). */
    this._phaserObj = null;

    /** Groups this sprite belongs to. */
    this._groups = new Set();

    /** Whether this sprite is alive. */
    this.alive = true;
  }

  /** Called each frame. Override in subclass. */
  update() {}

  /** Remove this sprite from all groups and destroy the Phaser object. */
  kill() {
    this.alive = false;
    for (const g of this._groups) {
      g.remove(this);
    }
    this._groups.clear();
    if (this._phaserObj) {
      this._phaserObj.destroy();
      this._phaserObj = null;
    }
  }

  /**
   * Add this sprite to one or more groups.
   * Called as: super().__init__(group1, group2, ...)  in pygame style.
   */
  add(...groups) {
    for (const g of groups) {
      g.add(this);
    }
  }

  /**
   * Ensure this sprite has a Phaser game object in the scene.
   * Called internally by Group.draw().
   */
  _ensurePhaserObj() {
    if (!_scene || this._phaserObj) return;

    if (this.image && this.image._imagePath) {
      // Image sprite
      const key = this.image._assetKey || _assetKey(this.image._imagePath);
      if (_scene.textures.exists(key)) {
        this._phaserObj = _scene.add.image(this.rect.x, this.rect.y, key);
        this._phaserObj.setOrigin(0, 0);
        // Sync rect dimensions from the actual texture
        this.rect.width = this._phaserObj.width;
        this.rect.height = this._phaserObj.height;
      }
    } else if (this.image && this.image._textContent != null) {
      // Text sprite
      this._phaserObj = _scene.add.text(this.rect.x, this.rect.y, this.image._textContent, {
        fontFamily: this.image._fontName || 'sans-serif',
        fontSize: `${this.image._fontSize || 16}px`,
        color: this.image._textColor || '#ffffff',
      });
      this._phaserObj.setOrigin(0, 0);
      this.rect.width = this._phaserObj.width;
      this.rect.height = this._phaserObj.height;
    }
  }

  /** Sync the Phaser game object position (and any pg.transform state) from this
   *  sprite's rect/image each frame. */
  _syncPosition() {
    if (!this._phaserObj) return;
    this._phaserObj.x = this.rect.x;
    this._phaserObj.y = this.rect.y;
    const img = this.image;
    if (img) {
      if (img._scaleW != null && this._phaserObj.setDisplaySize) {
        this._phaserObj.setDisplaySize(img._scaleW, img._scaleH);
      }
      if (img._angle != null && this._phaserObj.setAngle) {
        this._phaserObj.setAngle(img._angle);
      }
      if ((img._flipX != null || img._flipY != null) && this._phaserObj.setFlip) {
        this._phaserObj.setFlip(!!img._flipX, !!img._flipY);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// pg.sprite — Group, collision helpers
// ---------------------------------------------------------------------------

class Group {
  constructor() {
    this._members = new Set();
    _allGroups.add(this);
  }

  /** Add one or more sprites to the group. */
  add(...sprites) {
    for (const s of sprites) {
      this._members.add(s);
      s._groups.add(this);
    }
  }

  /** Remove a sprite from the group. */
  remove(s) {
    this._members.delete(s);
    s._groups.delete(this);
  }

  /** Check if a sprite is in this group. */
  has(s) {
    return this._members.has(s);
  }

  /** Call update() on all sprites. */
  update(...args) {
    for (const s of this._members) {
      s.update(...args);
    }
  }

  /**
   * Draw all sprites — ensures each has a Phaser game object,
   * then syncs positions.
   */
  draw(surface) {
    for (const s of this._members) {
      if (!s.alive) continue;
      s._ensurePhaserObj();
      s._syncPosition();

      // Handle image changes (e.g., animation frame swap)
      if (s._phaserObj && s.image && s.image._textContent != null) {
        // Text surface — update text if changed
        if (s._phaserObj.type === 'Text') {
          s._phaserObj.setText(s.image._textContent);
          s._phaserObj.setStyle({
            fontFamily: s.image._fontName || 'sans-serif',
            fontSize: `${s.image._fontSize || 16}px`,
            color: s.image._textColor || '#ffffff',
          });
        }
      }
    }
  }

  /** Return an array of all sprites in this group. */
  sprites() {
    return Array.from(this._members);
  }

  /** Return the number of sprites. */
  get length() {
    return this._members.size;
  }

  /** Empty the group, optionally killing all sprites. */
  empty() {
    for (const s of this._members) {
      s._groups.delete(this);
    }
    this._members.clear();
  }

  /** Iterate over sprites. */
  [Symbol.iterator]() {
    return this._members[Symbol.iterator]();
  }
}

export const sprite = {
  Sprite,
  Rect,

  /** Create a new sprite group. */
  Group() {
    return new Group();
  },

  /**
   * Find sprites in `group` that collide with `spr`.
   * If `dokill` is true, kill colliding sprites.
   */
  spritecollide(spr, group, dokill, collided = null) {
    const hits = [];
    for (const member of group.sprites()) {
      if (member === spr) continue;
      const collides = collided
        ? collided(spr, member)
        : spr.rect.colliderect(member.rect);
      if (collides) {
        hits.push(member);
        if (dokill) member.kill();
      }
    }
    return hits;
  },

  /**
   * Detect collisions between two groups.
   * Returns a dict mapping sprites from g1 to lists of colliding sprites from g2.
   */
  groupcollide(g1, g2, dokill1, dokill2) {
    const result = {};
    const toKill1 = new Set();
    const toKill2 = new Set();

    for (const s1 of g1.sprites()) {
      const hits = [];
      for (const s2 of g2.sprites()) {
        if (s1.rect.colliderect(s2.rect)) {
          hits.push(s2);
          if (dokill1) toKill1.add(s1);
          if (dokill2) toKill2.add(s2);
        }
      }
      if (hits.length > 0) {
        result[s1] = hits;
      }
    }

    for (const s of toKill1) s.kill();
    for (const s of toKill2) s.kill();

    return result;
  },

  /**
   * Check if a single sprite collides with any member of a group.
   */
  spritecollideany(spr, group) {
    for (const member of group.sprites()) {
      if (member === spr) continue;
      if (spr.rect.colliderect(member.rect)) return member;
    }
    return null;
  },
};

// ---------------------------------------------------------------------------
// pg.physics — optional arcade physics wrapper
// ---------------------------------------------------------------------------

export const physics = {
  /**
   * Attach a physics body to a sprite.
   * Requires the Phaser scene to have arcade physics enabled.
   */
  body(spr) {
    if (!_scene || !_scene.physics) return;
    spr._ensurePhaserObj();
    if (spr._phaserObj) {
      _scene.physics.add.existing(spr._phaserObj);
    }
  },

  /**
   * Set up a collision between two sprites or groups.
   */
  collide(a, b, callback = null) {
    if (!_scene || !_scene.physics) return;

    // Resolve Phaser game objects from our sprites/groups
    const resolveObj = (thing) => {
      if (thing instanceof Sprite) {
        thing._ensurePhaserObj();
        return thing._phaserObj;
      }
      if (thing instanceof Group) {
        // Create a Phaser group from our group's members
        const pGroup = _scene.add.group();
        for (const s of thing.sprites()) {
          s._ensurePhaserObj();
          if (s._phaserObj) pGroup.add(s._phaserObj);
        }
        return pGroup;
      }
      return thing;
    };

    const objA = resolveObj(a);
    const objB = resolveObj(b);

    if (objA && objB) {
      _scene.physics.add.collider(objA, objB, callback);
    }
  },
};

// ---------------------------------------------------------------------------
// Color utilities
// ---------------------------------------------------------------------------

/**
 * Convert a pygame-style color to a Phaser hex number.
 * Accepts: [r, g, b], [r, g, b, a], "#rrggbb", or a number.
 */
function _colorToHex(color) {
  if (typeof color === 'number') return color;
  if (typeof color === 'string') {
    if (color.startsWith('#')) return parseInt(color.slice(1), 16);
    return 0xffffff;
  }
  if (Array.isArray(color)) {
    const r = color[0] & 0xff;
    const g = color[1] & 0xff;
    const b = color[2] & 0xff;
    return (r << 16) | (g << 8) | b;
  }
  return 0xffffff;
}

/**
 * Convert a pygame-style color to a CSS color string.
 */
function _colorToCSS(color) {
  if (typeof color === 'string') return color;
  if (typeof color === 'number') {
    return `#${color.toString(16).padStart(6, '0')}`;
  }
  if (Array.isArray(color)) {
    if (color.length >= 4) {
      return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${color[3] / 255})`;
    }
    return `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
  }
  return '#ffffff';
}

/**
 * Convert a Phaser hex color to a CSS "#rrggbb" string.
 */
function _hexToCSS(hex) {
  return `#${hex.toString(16).padStart(6, '0')}`;
}

/**
 * Normalize a rect-like argument to a Rect instance.
 */
function _normalizeRect(r) {
  if (r instanceof Rect) return r;
  if (Array.isArray(r)) return new Rect(r[0], r[1], r[2], r[3]);
  if (r && typeof r.x === 'number') {
    return new Rect(r.x, r.y, r.width || r.w || 0, r.height || r.h || 0);
  }
  return new Rect(0, 0, 0, 0);
}

// ---------------------------------------------------------------------------
// PygameScene — the Phaser Scene that bridges pygame API to Phaser
// ---------------------------------------------------------------------------

export class PygameScene extends Phaser.Scene {
  /**
   * @param {Object} config
   * @param {Function} config.preloadFn  Called after assets are queued (optional)
   * @param {Function} config.createFn   Called once the scene is ready
   * @param {Function} config.updateFn   Called every frame
   * @param {string}   config.backgroundColor  CSS color for the background
   */
  constructor(config = {}) {
    super({ key: 'PygameScene' });
    this._preloadFn = config.preloadFn || null;
    this._createFn = config.createFn || null;
    this._updateFn = config.updateFn || null;
    this._bgColor = config.backgroundColor || '#000000';

    /** Graphics object for draw.rect/circle/line calls. */
    this._gfx = null;

    /** Blit queue — populated by Surface.blit(), drawn each frame. */
    this._blitQueue = [];

    /** Phaser game objects created via blit (keyed by a blit index for reuse). */
    this._blitObjects = [];
  }

  /** Return (or create) the shared Graphics object for primitive drawing. */
  _getGraphics() {
    if (!this._gfx) {
      this._gfx = this.add.graphics();
      this._gfx.setDepth(1000); // draw primitives on top
    }
    return this._gfx;
  }

  // --- Phaser lifecycle: preload ---
  preload() {
    // Load all images registered via pg.image.load()
    for (const path of _preloadPaths) {
      const key = _assetKey(path);
      if (!this.textures.exists(key)) {
        this.load.image(key, path);
      }
    }

    // Load all audio registered via pg.mixer
    for (const path of _audioPreloadPaths) {
      const key = _assetKey(path);
      this.load.audio(key, path);
    }

    // Let the game code do additional preloading
    if (this._preloadFn) {
      this._preloadFn(this);
    }
  }

  // --- Phaser lifecycle: create ---
  create() {
    // Store the scene reference globally
    _scene = this;

    // Set background color
    this.cameras.main.setBackgroundColor(this._bgColor);

    // Initialize the key map now that Phaser is fully available
    _initKeyMap();

    // --- Input: keyboard ---
    this.input.keyboard.on('keydown', (evt) => {
      const pgKey = _translateKey(evt.keyCode);
      _keysDown[pgKey] = true;
      _eventQueue.push({
        type: KEYDOWN,
        key: pgKey,
        _raw: evt,
      });
    });

    this.input.keyboard.on('keyup', (evt) => {
      const pgKey = _translateKey(evt.keyCode);
      _keysDown[pgKey] = false;
      _eventQueue.push({
        type: KEYUP,
        key: pgKey,
        _raw: evt,
      });
    });

    // --- Input: mouse ---
    this.input.on('pointermove', (pointer) => {
      _mousePos.x = pointer.x;
      _mousePos.y = pointer.y;
    });

    this.input.on('pointerdown', (pointer) => {
      _mousePos.x = pointer.x;
      _mousePos.y = pointer.y;
      if (pointer.button >= 0 && pointer.button <= 2) _mouseButtons[pointer.button] = true;
      _eventQueue.push({
        type: MOUSEBUTTONDOWN,
        pos: [pointer.x, pointer.y],
        button: pointer.button === 0 ? 1 : (pointer.button === 2 ? 3 : 2),
      });
    });

    this.input.on('pointerup', (pointer) => {
      _mousePos.x = pointer.x;
      _mousePos.y = pointer.y;
      if (pointer.button >= 0 && pointer.button <= 2) _mouseButtons[pointer.button] = false;
      _eventQueue.push({
        type: MOUSEBUTTONUP,
        pos: [pointer.x, pointer.y],
        button: pointer.button === 0 ? 1 : (pointer.button === 2 ? 3 : 2),
      });
    });

    // Let the game code run its create/setup logic
    if (this._createFn) {
      this._createFn(this);
    }
  }

  // --- Phaser lifecycle: update ---
  update(time, delta) {
    // Clear the graphics layer each frame (for draw.* calls)
    if (this._gfx) {
      this._gfx.clear();
    }

    // Clear previous blit objects visibility
    for (const obj of this._blitObjects) {
      obj.setVisible(false);
    }
    this._blitQueue.length = 0;

    // Run the game's update function
    if (this._updateFn) {
      this._updateFn(time, delta);
    }

    // Process blit queue — create or reuse Phaser game objects
    for (let i = 0; i < this._blitQueue.length; i++) {
      const blit = this._blitQueue[i];

      if (blit.source._textContent != null) {
        // Text blit
        let obj = this._blitObjects[i];
        if (!obj || obj.type !== 'Text') {
          if (obj) obj.destroy();
          obj = this.add.text(blit.x, blit.y, blit.source._textContent, {
            fontFamily: blit.source._fontName || 'sans-serif',
            fontSize: `${blit.source._fontSize || 16}px`,
            color: blit.source._textColor || '#ffffff',
          });
          obj.setOrigin(0, 0);
          this._blitObjects[i] = obj;
        } else {
          obj.setText(blit.source._textContent);
          obj.setPosition(blit.x, blit.y);
          obj.setStyle({
            fontFamily: blit.source._fontName || 'sans-serif',
            fontSize: `${blit.source._fontSize || 16}px`,
            color: blit.source._textColor || '#ffffff',
          });
          obj.setVisible(true);
        }
      } else if (blit.source._imagePath) {
        // Image blit
        const assetKey = blit.source._assetKey || _assetKey(blit.source._imagePath);
        let obj = this._blitObjects[i];
        if (!obj || obj.type !== 'Image' || obj.texture.key !== assetKey) {
          if (obj) obj.destroy();
          if (this.textures.exists(assetKey)) {
            obj = this.add.image(blit.x, blit.y, assetKey);
            obj.setOrigin(0, 0);
            this._blitObjects[i] = obj;
          }
        } else {
          obj.setPosition(blit.x, blit.y);
          obj.setVisible(true);
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// createGame() — top-level entry point
// ---------------------------------------------------------------------------

/**
 * Create and start a Phaser game with a PygameScene.
 *
 * @param {Object} config
 * @param {number}   config.width          Canvas width (default: 800)
 * @param {number}   config.height         Canvas height (default: 600)
 * @param {Function} config.preloadFn      Preload callback (optional)
 * @param {Function} config.createFn       Create/setup callback
 * @param {Function} config.updateFn       Per-frame update callback
 * @param {string}   config.backgroundColor  Background color (default: '#000000')
 * @param {number}   config.fps            Target frame rate (default: 60)
 * @param {string|HTMLElement} config.parent  Parent element or selector
 * @param {boolean}  config.physics        Enable arcade physics (default: false)
 * @returns {Phaser.Game}
 */
export function createGame(config = {}) {
  const width = config.width || _screenWidth;
  const height = config.height || _screenHeight;
  const fps = config.fps || 60;
  const bgColor = config.backgroundColor || '#000000';
  const usePhysics = config.physics || false;

  const scene = new PygameScene({
    preloadFn: config.preloadFn || null,
    createFn: config.createFn || null,
    updateFn: config.updateFn || null,
    backgroundColor: bgColor,
  });

  const phaserConfig = {
    type: Phaser.AUTO,
    width,
    height,
    parent: config.parent || 'game-container',
    backgroundColor: bgColor,
    fps: {
      target: fps,
      forceSetTimeOut: false,
    },
    scene: scene,
    audio: {
      disableWebAudio: false,
    },
  };

  // Add arcade physics if requested
  if (usePhysics) {
    phaserConfig.physics = {
      default: 'arcade',
      arcade: {
        gravity: { y: 0 },
        debug: false,
      },
    };
  }

  const game = new Phaser.Game(phaserConfig);
  return game;
}

// ---------------------------------------------------------------------------
// Convenience: the pg namespace object
// ---------------------------------------------------------------------------

/**
 * The `pg` object bundles everything into a single pygame-like namespace.
 * Compiled code can use either:
 *   import { display, sprite, Rect } from 'pylevate-game-runtime';
 *   import pg from 'pylevate-game-runtime';
 */
const pg = {
  // Event type constants
  QUIT,
  KEYDOWN,
  KEYUP,
  MOUSEBUTTONDOWN,
  MOUSEBUTTONUP,
  MOUSEMOTION,

  // Key constants
  K_LEFT, K_RIGHT, K_UP, K_DOWN,
  K_SPACE, K_RETURN, K_ESCAPE,
  K_a, K_b, K_c, K_d, K_e, K_f, K_g, K_h, K_i, K_j, K_k, K_l, K_m,
  K_n, K_o, K_p, K_q, K_r, K_s, K_t, K_u, K_v, K_w, K_x, K_y, K_z,
  K_0, K_1, K_2, K_3, K_4, K_5, K_6, K_7, K_8, K_9,

  // Core functions
  init,

  // Modules
  display,
  time,
  event,
  key,
  mouse,
  image,
  mixer,
  font,
  draw,
  sprite,
  physics,

  // Classes
  Rect,
  Sprite,
  Surface,

  // Game creation
  PygameScene,
  createGame,
};

export { Surface };
export default pg;

// ---------------------------------------------------------------------------
// random_randrange — utility carried over from the stub
// ---------------------------------------------------------------------------

export function random_randrange(start, end) {
  if (end === undefined) { end = start; start = 0; }
  return Math.floor(Math.random() * (end - start)) + start;
}
