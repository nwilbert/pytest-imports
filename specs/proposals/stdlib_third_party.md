# Spec: `stdlib()` and `third_party()` targets

Status: proposal.

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
    scope('myapp.plugins'): must_only_import(['json', 'pathlib'], among=stdlib()),
})
```

## Semantics

- **Stdlib membership** is `dot_path.parts[0] in sys.stdlib_module_names`
  (Python ≥ 3.10, which matches `requires-python`). The set includes
  private modules (`_thread`) and `__future__`.
- **Internal wins.** If a project has its own `logging` package, imports
  of it match `internal()` only, which keeps the three classes
  disjoint.
- **Relative imports** inside a package resolve under that package, so
  they are internal even when the imported module does not exist. The
  one exception is a relative import of a missing module from a
  top-level module (`from . import missing` in `src/foo.py`). It
  resolves to the bare name `missing` and falls through to
  classification by name. This is accepted: the import is broken anyway.
- **Interpreter-dependent.** Classification follows the interpreter
  running pytest: `tomllib` is third-party on 3.10, and `distutils` is
  third-party on 3.12+. Document this. Where it matters (e.g. a
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
- Failure messages for `must_not_import(third_party())` and
  `must_only_import(..., among=third_party())`.

Architecture test (`test/arch/test_imports.py`): tighten
`scope('pytest_imports', without='plugin'): must_not_import('pytest')`
to `must_not_import(third_party())`. This is the motivating rule,
dogfooded.

## Docs

- `README.md`: two rows in the API table, plus a short example section
  covering usage and the interpreter-dependence caveat. Replace the
  vague "Internal vs. external imports" paragraph with a description of
  the three classes.
- `GLOSSARY.md`: add **stdlib import** and **third-party import**
  (splitting **external import**), and list the new targets under
  **target**.
- `AGENTS.md`: update the `Target` union in the architecture notes.

## Out of scope

- **`external()`** (= stdlib ∪ third-party). Lists already cover it
  wherever a tuple of targets is accepted. The one gap is `among`, which
  takes a single target. If that gap matters, widen `among` to accept a
  list rather than adding more target types.
- **Configurable stdlib set** (e.g. for checking against a different
  Python version than the one running pytest). Add only if someone asks.
- **Ruff compilation**: if the `ruff_compile.md` proposal is
  implemented, it should skip `third_party()`, because it is an open set
  that `banned-api` cannot express.
