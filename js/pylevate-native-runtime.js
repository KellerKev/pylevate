/**
 * PyLevate Native Runtime — Wraps Capacitor plugins with Python-style API.
 *
 * Users import from 'pylevate.native', never from '@capacitor/*' directly.
 * The compiler rewrites these imports to direct Capacitor imports for
 * Capacitor builds. This file serves as the web fallback (no-op stubs).
 */

// Web fallback stubs — these do nothing in browser, only work in Capacitor
const _warn = (plugin, method) =>
  console.warn(`[PyLevate] ${plugin}.${method}() requires a native device (Capacitor).`);

export const Camera = {
  async getPhoto(options = {}) {
    _warn('Camera', 'getPhoto');
    return { webPath: '', format: 'jpeg' };
  },
  async get_photo(options = {}) { return Camera.getPhoto(options); },
};

export const Geolocation = {
  async getCurrentPosition(options = {}) {
    _warn('Geolocation', 'getCurrentPosition');
    return { coords: { latitude: 0, longitude: 0, accuracy: 0 } };
  },
  async get_current_position(options = {}) { return Geolocation.getCurrentPosition(options); },
};

export const Haptics = {
  async impact(options = {}) {
    _warn('Haptics', 'impact');
  },
};

export const Storage = {
  async get(options = {}) {
    // Use localStorage as web fallback
    const val = localStorage.getItem(options.key);
    return { value: val };
  },
  async set(options = {}) {
    localStorage.setItem(options.key, typeof options.value === 'string' ? options.value : JSON.stringify(options.value));
  },
  async remove(options = {}) {
    localStorage.removeItem(options.key);
  },
};

export const Share = {
  async share(options = {}) {
    if (navigator.share) {
      return navigator.share(options);
    }
    _warn('Share', 'share');
    return {};
  },
};

export const PushNotifications = {
  async register() {
    _warn('PushNotifications', 'register');
  },
  async getDeliveredNotifications() {
    _warn('PushNotifications', 'getDeliveredNotifications');
    return { notifications: [] };
  },
  async get_delivered_notifications() { return PushNotifications.getDeliveredNotifications(); },
};
