/**
 * PyLevate HMR Client — injected in dev mode only.
 * Connects to the HMR WebSocket server and handles hot reloads.
 */
(function() {
  const HMR_PORT = window.__PYLEVATE_HMR_PORT__ || 3001;
  const ws = new WebSocket(`ws://localhost:${HMR_PORT}`);

  ws.onopen = () => {
    console.log('[PyLevate] HMR connected');
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case 'reload':
        console.log('[PyLevate] Full reload');
        // Let the runtime snapshot store state (dev-mode rehydration).
        window.dispatchEvent(new Event('pylevate:before-reload'));
        location.reload();
        break;

      case 'css':
        console.log('[PyLevate] CSS update');
        // Reload all stylesheets
        document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
          const url = new URL(link.href);
          url.searchParams.set('_hmr', Date.now());
          link.href = url.toString();
        });
        break;

      case 'error':
        showErrorOverlay(data);
        break;

      case 'clear-error':
        clearErrorOverlay();
        break;
    }
  };

  ws.onclose = () => {
    console.log('[PyLevate] HMR disconnected, retrying in 2s...');
    setTimeout(() => location.reload(), 2000);
  };

  function showErrorOverlay(data) {
    clearErrorOverlay();
    const overlay = document.createElement('div');
    overlay.id = '__pylevate_error_overlay__';
    overlay.style.cssText = `
      position: fixed; inset: 0; z-index: 99999;
      background: rgba(0,0,0,0.92); color: #ff6b6b;
      font-family: 'SF Mono', Monaco, Consolas, monospace;
      font-size: 14px; padding: 2rem; overflow: auto;
    `;
    overlay.innerHTML = `
      <div style="max-width: 900px; margin: 0 auto;">
        <h2 style="color: #ff6b6b; margin: 0 0 1rem;">Compile Error</h2>
        <div style="color: #ccc; margin-bottom: 0.5rem;">
          <strong>${data.file || 'unknown'}</strong>:${data.line || '?'}:${data.col || '?'}
        </div>
        <pre style="background: #1a1a2e; padding: 1rem; border-radius: 6px; color: #e2e2e2; overflow-x: auto; white-space: pre-wrap;">${escapeHtml(data.message || 'Unknown error')}</pre>
        ${data.source ? `<h3 style="color: #888; margin: 1rem 0 0.5rem;">Python Source</h3><pre style="background: #1a1a2e; padding: 1rem; border-radius: 6px; color: #e2e2e2; overflow-x: auto;">${escapeHtml(data.source)}</pre>` : ''}
        ${data.js ? `<h3 style="color: #888; margin: 1rem 0 0.5rem;">Compiled JS (partial)</h3><pre style="background: #1a1a2e; padding: 1rem; border-radius: 6px; color: #e2e2e2; overflow-x: auto;">${escapeHtml(data.js)}</pre>` : ''}
        <p style="color: #666; margin-top: 1.5rem;">Fix the error and save — this overlay will dismiss automatically.</p>
      </div>
    `;
    document.body.appendChild(overlay);
  }

  function clearErrorOverlay() {
    const existing = document.getElementById('__pylevate_error_overlay__');
    if (existing) existing.remove();
  }

  function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
})();
