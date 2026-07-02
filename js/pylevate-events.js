/**
 * PyLevate Event Bus — cross-boundary communication between game and UI.
 *
 * Used in hybrid mode: game scenes emit events, Preact components subscribe.
 * Works with @preact/signals for reactive UI updates.
 *
 * Usage from game code:
 *   game_events.emit('score_change', 100)
 *
 * Usage from UI code:
 *   game_events.on('score_change', (val) => score.value = val)
 */

class EventBus {
  constructor() {
    this._listeners = new Map();
  }

  /**
   * Subscribe to an event. Returns an unsubscribe function.
   */
  on(event, callback) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, new Set());
    }
    this._listeners.get(event).add(callback);
    return () => this._listeners.get(event)?.delete(callback);
  }

  /**
   * Subscribe to an event, auto-remove after first call.
   */
  once(event, callback) {
    const unsub = this.on(event, (...args) => {
      unsub();
      callback(...args);
    });
    return unsub;
  }

  /**
   * Emit an event with optional data.
   */
  emit(event, ...args) {
    const listeners = this._listeners.get(event);
    if (listeners) {
      for (const cb of listeners) {
        try {
          cb(...args);
        } catch (e) {
          console.error(`[game_events] Error in listener for '${event}':`, e);
        }
      }
    }
  }

  /**
   * Remove all listeners for an event, or all listeners if no event specified.
   */
  off(event, callback) {
    if (callback) {
      this._listeners.get(event)?.delete(callback);
    } else if (event) {
      this._listeners.delete(event);
    } else {
      this._listeners.clear();
    }
  }
}

// Singleton — shared across game and UI modules
export const game_events = new EventBus();
export default game_events;

// Expose the singleton on globalThis so an external bridge can hook the *same*
// event bus the compiled app uses.
if (typeof globalThis !== "undefined") globalThis.__pylevate_events = game_events;
