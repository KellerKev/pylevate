"""The document corpus for the RAG template.

The pipeline ships only .py/.js/.css sources, so the corpus lives in a Python
string. Swap CORPUS for your own text (or several module-level strings).
"""

CORPUS = """
PyLevate is a Python-syntax full-stack framework that compiles to Preact for
web apps and Phaser for 2D games. You write standard Python — classes, dicts,
decorators, pygame calls — and the compiler transforms it into optimized
JavaScript bundles. There is no Python interpreter at runtime; everything
compiles away at build time.

Components are classes extending Component. The template is a Python dict
that compiles to Preact h() calls at build time. Reactive state uses
@preact/signals under the hood: state(x) compiles to signal(x), with reads
and writes going through .value automatically. Cross-component state lives in
Store subclasses, which are singletons by convention. In development, JSON
serializable store state survives full reloads via sessionStorage.

Routing uses App and Router: App(router=Router([('/', Home)])) mounts a
preact-router under the hood. Page components use the @page decorator to set
the document title and declare their route. Route parameters like
/profile/:id arrive as props on the page component.

Game mode uses a pygame-compatible API. import pylevate.game as pg mirrors
pygame's namespace. The same code runs locally with real pygame for rapid
iteration, then compiles to Phaser for web and mobile deployment. The
compiler hoists asset loads into Phaser's preload, setup code into create,
and the while-loop body into update.

Scoped CSS uses css() inside a component. Class names receive a SHA1-based
suffix derived from the file path, so .card in button.py can never collide
with .card in card.py. Global styles go in a plain CSS file using CSS custom
properties.

Production builds run pylevate build: bundles are minified and file names
carry a content hash, with index.html rewritten to match, so output can be
served with long-lived cache headers. Development uses pylevate dev, a live
reload server with a compile-error overlay and store-state restore.

For LLM apps, pylevate.chat ships chat UI components (ChatWindow,
MessageList, ChatInput, ToolCallCard) and pylevate.ai ships AIClient, a
streaming client for OpenAI-compatible APIs and Anthropic, with client-side
tool calling and an embeddings helper. The dev server can proxy LLM requests
so API keys stay out of the browser.

Mobile deployment uses Capacitor. pylevate init --mobile pre-configures the
project; pylevate mobile ios builds, syncs, and opens Xcode. Native
capabilities like Camera and Geolocation are imported from pylevate.native
and compile to Capacitor plugin calls.
"""
