# Spec: `stdlib()` and `third_party()` targets

## Motivation

The most common external-dependency rule is "this package must not
depend on anything outside the standard library", e.g. a pure domain
layer or a vendorable utility package. Today the only way to state it is
to list every third-party package in `must_not_import([...])`, and that
list goes stale as soon as someone adds a dependency.

Two new structured targets close the gap. Together with `internal()`
they split every import into three disjoint classes:

| target          | matches                                              |
| --------------- | ---------------------------------------------------- |
| `internal()`    | resolves to a module under the source roots          |
| `stdlib()`      | not internal, top-level name is a stdlib module      |
| `third_party()` | not internal, not stdlib                             |

## Usage

```python
from pytest_imports import (
    internal, must_not_import, must_not_import_private, must_only_import,
    project, scope, stdlib, third_party,
)

imports.check({
    # Pure core: stdlib and internal imports only.
    scope('myapp.domain'): must_not_import(third_party()),
    # The only third-party dependency the API layer may use is fastapi.
    scope('myapp.api'): must_only_import('fastapi', among=third_party()),
    # Ignore private names reached through the stdlib (_thread, os._exit, …).
    project(): must_not_import_private([internal(), third_party()]),
    # The sandboxed plugin layer may only use these stdlib modules.
    scope('myapp.plugins'): must_only_import(
        ['__future__', 'json', 'pathlib'], among=stdlib()
    ),
})
```

## Semantics

- **Stdlib membership** is `dot_path.parts[0] in sys.stdlib_module_names`
  (Python ≥ 3.10, which matches `requires-python`). The set includes
  private modules (`_thread`) and `__future__`. The latter means a
  stdlib allowlist (`must_only_import([...], among=stdlib())`) must
  list `'__future__'` to permit `from __future__ import annotations`.
  Excluding it from `stdlib()` instead would push it into
  `third_party()`, which is worse.
- **Internal wins.** If a project has its own `logging` package, imports
  of it match `internal()` only, which keeps the three classes
  disjoint.
- **Relative imports** are always internal: they resolve under an
  existing package, even when the imported module does not exist. The
  parser skips (with a warning) relative imports that go beyond the
  top-level package, which Python rejects anyway.
- **Interpreter-dependent.** Classification follows the version of the
  interpreter running pytest: `tomllib` is third-party on 3.10, and
  `distutils` is third-party on 3.12+. It does not depend on the
  platform: `sys.stdlib_module_names` lists platform-specific modules
  (`winreg`, `fcntl`) everywhere. Document this. Where it matters (e.g. a
  `try: import tomllib / except ImportError: import tomli` fallback),
  phrase the rule as an allowlist, not a ban:
  `must_only_import(['tomllib', 'tomli'], among=third_party())`.

## Code changes

`query.py`:

- Add `class Stdlib` and `class ThirdParty` (frozen, fieldless, like
  `Internal`), extend `Target = str | Descendants | Internal | Stdlib | ThirdParty`,
  and add the factories `stdlib()` and `third_party()`.
- Extract the existing prefix walk from the `Internal()` arm of
  `_match_target` into `_is_internal(dot_path, root_node)`, and add
  `_is_stdlib(dot_path)` (the `sys.stdlib_module_names` check). The new
  arms become:

  ```python
  case Stdlib():
      return not _is_internal(dot_path, root_node) and _is_stdlib(dot_path)
  case ThirdParty():
      return not _is_internal(dot_path, root_node) and not _is_stdlib(dot_path)
  ```

- `_format_target`: `'any stdlib module'`, `'any third-party module'`.

`__init__.py`: export `stdlib` and `third_party`.

## Tests

Unit tests (`test/unit/test_query.py`):

- `os`, `os.path`, `_thread` and `__future__` match `stdlib()`. `requests`
  and `tomli` match `third_party()`.
- A project package named `logging` matches `internal()` only.
- A relative import of a missing module inside a package (`from .json
  import x`) is internal, not stdlib.
- Every import in a mixed fixture matches exactly one of the three
  targets.
- `tomllib` matches `stdlib()` on 3.11+ and `third_party()` on 3.10
  (branch on `sys.version_info`; the `pytest_compat` matrix covers
  both).
- Failure messages (`test/unit/test_plugin.py`) for `must_not_import(third_party())` and
  `must_only_import(..., among=third_party())`.

Architecture test (`test/arch/test_imports.py`): tighten
`scope('pytest_imports', without='plugin'): must_not_import('pytest')`
to `must_not_import(third_party())`, and add
`scope('pytest_imports'): must_only_import('pytest', among=third_party())`
so the plugin module is covered too. This is the motivating rule,
dogfooded in both its ban and allowlist forms.

## Docs

- `README.md`: two rows in the API table, plus a short example section
  covering usage and the interpreter-dependence caveat. Replace the
  vague "Internal vs. external imports" paragraph with a description of
  the three classes.
- `GLOSSARY.md`: add **stdlib import** and **third-party import**
  (splitting **external import**), and list the new targets under
  **target**. That entry's "accepted by `must_import` and
  `must_not_import`" is already out of date; list all predicates that
  take targets.
- `AGENTS.md`: update the `Target` union in the architecture notes.

## Out of scope

- **`external()`** (= stdlib ∪ third-party). A list covers it wherever
  a list of targets is combined disjunctively (`must_not_import`,
  `must_not_import_private`, `must_only_import`'s `allowed`). There are
  two gaps: `among` takes a single target, and `must_import` is
  conjunctive, so `must_import([stdlib(), third_party()])` requires
  both. Neither looks important; if one does, widen `among` to accept a
  list rather than adding more target types.
- **Configurable stdlib set** (e.g. for checking against a different
  Python version than the one running pytest). Add only if someone asks.
- **Ruff compilation**: if the `ruff_compile.md` proposal is
  implemented, it should skip rules using either new target at first.
  `third_party()` is an open set that `banned-api` cannot express.
  `stdlib()` could expand to `sys.stdlib_module_names` minus names
  shadowed by internal modules, but the generated config would then
  depend on the Python version, so `matches_disk()` could disagree
  across the CI matrix. Neither works as `among` for `must_only_import`,
  whose compilation walks the model, and the model does not contain
  external modules.
