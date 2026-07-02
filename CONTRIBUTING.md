# Contributing to PyLevate

Thanks for your interest in PyLevate! Whether you're fixing a bug, sharpening the
docs, or building out the compiler, contributions are very welcome. This guide gets
you from clone to green tests quickly.

## Ground rules

- Be kind and constructive. All participation is governed by our
  [Code of Conduct](CODE_OF_CONDUCT.md).
- Small, focused pull requests are easier to review and land faster than large ones.
- Every change that touches the compiler or runtime should come with tests.

## Getting set up

PyLevate uses [Pixi](https://pixi.sh) to manage its Python + Node toolchain, so you
don't have to install them yourself.

```bash
# Clone your fork
git clone https://github.com/<you>/pylevate.git
cd pylevate

# Install the environment
pixi install

# Try it out — the zero-config playground compiles PyLevate live in your browser
pixi run python -m pylevate.cli playground   # → http://localhost:4000
```

## Running the tests

The full suite runs in the `test` environment:

```bash
pixi run -e test test
```

Please make sure the suite is green before opening a pull request. New behavior in
the compiler (`pylevate/compiler/`) or runtime (`pylevate/runtime/`, `js/`) should
be covered by a test under `tests/`.

## Project layout

A quick map of the tree (see [README.md](README.md#project-structure) for the full
tour):

| Path | What lives here |
|------|-----------------|
| `pylevate/compiler/` | Python → JavaScript compiler (AST walker, CSS scoper, loop hoister) |
| `pylevate/runtime/`   | Python-side runtime shims (`Component`, signals, game loop) |
| `js/`                 | JavaScript runtime + baselib shipped with compiled apps |
| `pylevate/templates/` | `init` scaffolding for `app` / `game` / `hybrid` / `dashboard` |
| `tests/`              | pytest suite (compiler + end-to-end) |

## Making a change

1. Branch off `main`: `git switch -c my-feature`.
2. Make your change and add or update tests.
3. Run `pixi run -e test test` and confirm everything passes.
4. Keep commit messages descriptive — explain the *why*, not just the *what*.
5. Open a pull request against `main`. CI will run the suite automatically.

### Compiler changes

The compiler favors **failing loudly over miscompiling silently**. If a Python
construct can't be represented faithfully in JavaScript, prefer a clear compile-time
error (via `self._error(node, ...)`) over emitting code that breaks at runtime. When
you fix a miscompilation, add a regression test that would have caught it.

## Reporting bugs and requesting features

Open an issue using one of the [templates](.github/ISSUE_TEMPLATE/). A minimal
PyLevate snippet that reproduces the problem — plus the JavaScript it compiled to —
makes bugs dramatically faster to fix.

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE) that covers the project.
