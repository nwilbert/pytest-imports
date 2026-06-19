# Spec: import placement (`at=`) and `external()` target

## Motivation

Today the model treats every import the same regardless of where the
statement physically sits. In practice, projects routinely care about
the distinction between:

- **top-level imports** — executed once when the module is loaded,
- **function-level imports** — deferred to call time (a.k.a. *lazy
  imports*), used to break cycles, defer optional heavy dependencies,
  or shorten startup time,
- **type-checking imports** — inside `if TYPE_CHECKING:`, executed only
  by static type checkers, free at runtime.

Concrete rules that users want to express:

- "No lazy imports of internal modules" — `myapp` core should be
  importable without surprises.
- "Heavy third-party deps (`pandas`, `tensorflow`) must only be imported
  lazily inside the CLI / request handlers."
- "Internal cycles must be broken with `TYPE_CHECKING`, never with
  function-level imports."
- "Required bootstrap imports must appear at module top — not hidden in
  a function."

Independently, `internal()` matches imports resolving inside the
configured source roots. There is no symmetric target for "everything
that is *not* internal" — stdlib and third-party. Adding `external()`
closes that gap and unlocks rules like "core layer must not depend on
any third-party package" without enumerating package names.

## Open questions — resolved in this spec

### Three placements as a flat partition, or `top` as a union?

**Flat partition.** The model exposes exactly three mutually exclusive
placement literals: `'top'`, `'type_checking'`, `'function'`. There is
no `top_unconditional` and no union alias.

This was considered both ways. The community treats `if TYPE_CHECKING:`
as a blessed pattern (stdlib member since 3.5.3, actively *promoted* by
ruff's `flake8-type-checking` rules), so a sentiment argument for
demoting it doesn't hold. The deciding factor is **ergonomics of the
default reading**:

- `must_import('foo', at='top')` should mean "a real, runtime import of
  `foo` exists at module top". If `'top'` included TYPE_CHECKING, the
  predicate would be satisfied by `if TYPE_CHECKING: import foo` — an
  import that never runs. Counterintuitive.
- `must_not_import('pandas', at='top')` should mean "no runtime
  top-level import of pandas". If `'top'` included TYPE_CHECKING, the
  rule would also forbid annotating a function parameter as
  `pandas.DataFrame` behind a TYPE_CHECKING block — usually fine and
  often desirable.

Users who want "anywhere but a function body" can write
`at=['top', 'type_checking']` — explicit, and the common per-placement
cases stay terse.

### Should we add `external()` to complement `internal()`?

**Yes.** Same dataclass-with-no-fields shape as `Internal`; matches
exactly the imports that `internal()` would *not* match. Together they
form a complete partition of the universe of imports the parser sees,
which is useful both for self-documenting rules and as a building block
for future predicates (e.g. `must_only_import(external())`).

### Should other top-level constructs get their own placement?

**No.** TYPE_CHECKING is exceptional because it changes runtime
semantics — the body never executes at runtime, full stop, signaled by
a unique easy-to-pattern-match AST shape. Every other top-level
construct (`try`/`except`, `if sys.version_info ...`, `if sys.platform`,
`if __name__ == '__main__'`, `with`, `match`, class bodies) executes at
module load time on at least one code path, and the conditions are
arbitrary expressions with no clean partition. Adding `top_conditional`,
`top_version_gated`, `top_platform_gated`, etc. is a slippery slope
with diminishing returns — most of those distinctions are better made
on the **target** axis (forbid importing `winreg` by name, forbid a
specific optional dependency) or by reading the AST in a custom check.

If real demand emerges for a "wrapped in any conditional" signal, the
cleanest extension is an **orthogonal** axis (e.g. a separate `when=`
option or a `conditional: bool` field) rather than expanding the
`at=` enumeration.

## Public API

### `at=` on predicates

```python
from pytest_imports import must_import, must_not_import, project, scope

def test_no_lazy_internal_imports(imports):
    imports.check({
        project(): must_not_import(internal(), at='function'),
    })

def test_heavy_deps_are_lazy(imports):
    imports.check({
        scope('myapp.cli'): [
            must_not_import('pandas', at='top'),
            must_not_import('tensorflow', at='top'),
        ],
    })

def test_cycles_broken_via_type_checking(imports):
    imports.check({
        scope('myapp.models'): must_not_import('myapp.services', at='function'),
    })

def test_bootstrap_at_top(imports):
    imports.check({
        'myapp.bootstrap': must_import('myapp.config', at='top'),
    })

def test_no_runtime_typing_imports(imports):
    # `typing` should only appear behind TYPE_CHECKING — never at
    # runtime top level, never function-level.
    imports.check({
        project(): must_not_import('typing', at=['top', 'function']),
    })
```

Updated signatures:

```python
Placement = Literal['top', 'type_checking', 'function']

def must_import(
    path: Target,
    *,
    via: Via | None = None,
    at: Placement | list[Placement] | None = None,
) -> MustImport: ...

def must_not_import(
    path: Target,
    *,
    via: Via | None = None,
    at: Placement | list[Placement] | None = None,
) -> MustNotImport: ...

def must_not_import_private(
    path: str | None = None,
    *,
    at: Placement | list[Placement] | None = None,
) -> MustNotImportPrivate: ...
```

`at=None` (the default) matches all placements — fully backwards
compatible.

### `external()` target

```python
from pytest_imports import external, internal, must_not_import, project, scope

def test_core_has_no_third_party_deps(imports):
    imports.check({
        scope('myapp.core'): must_not_import(external()),
    })

def test_all_lazy_imports_are_internal(imports):
    # External deps should be imported at module top, not deferred.
    imports.check({
        project(): must_not_import(external(), at='function'),
    })
```

Factory and dataclass:

```python
def external() -> External: ...

@dataclass(frozen=True)
class External:
    """Target matching any import resolving outside the configured source roots."""
```

Added to the `Target` union: `Target = str | Descendants | Internal | External`.

## Semantics

### Placement classification

For each import statement, the parser assigns exactly one of three
**placements**:

| Placement         | Statement is …                                                                                                                |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `'function'`      | nested inside a `def` or `async def` body, at any depth                                                                       |
| `'type_checking'` | at module top level **and** inside the `body` of an `if TYPE_CHECKING:` block (any nesting depth, but never inside a function) |
| `'top'`           | everything else — plain module top-level, class body, `try`/`except`, plain `if`, `with`, `match`, etc.                       |

Priority rules when classifications would overlap:

1. **Function wins.** An `import` inside a nested function inside an
   `if TYPE_CHECKING:` block is `'function'`, not `'type_checking'`.
   Function-level placement is contagious: once `_collect_imports`
   descends into a `FunctionDef` / `AsyncFunctionDef`, every import
   below that point is `'function'`.
2. **`else:` is not TYPE_CHECKING.** Only the `body` of a recognized
   `if TYPE_CHECKING:` block carries the `type_checking` placement;
   imports in its `orelse` revert to the surrounding placement.
3. **Nested TYPE_CHECKING blocks stay TYPE_CHECKING.** An
   `if TYPE_CHECKING:` inside another `if TYPE_CHECKING:` keeps the
   placement; the flag is a one-way switch.

### `TYPE_CHECKING` recognition

The parser recognizes `if TYPE_CHECKING:` blocks by inspecting the
condition's AST shape, regardless of how `TYPE_CHECKING` was imported:

| Source pattern                                          | AST `test`                                                          | Recognized                  |
| ------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------- |
| `from typing import TYPE_CHECKING`<br>`if TYPE_CHECKING:` | `ast.Name(id='TYPE_CHECKING')`                                      | yes                         |
| `import typing`<br>`if typing.TYPE_CHECKING:`           | `ast.Attribute(value=ast.Name(id='typing'), attr='TYPE_CHECKING')`  | yes                         |
| `import typing as t`<br>`if t.TYPE_CHECKING:`           | `ast.Attribute(attr='TYPE_CHECKING')` — any prefix                  | yes                         |
| `from typing import TYPE_CHECKING as TC`<br>`if TC:`    | `ast.Name(id='TC')`                                                 | **no** (limitation)         |
| `if not TYPE_CHECKING:`                                 | `ast.UnaryOp(...)`                                                  | **no** — body runs at runtime |
| `if TYPE_CHECKING and sys.version_info > ...:`          | `ast.BoolOp(...)`                                                   | **no** — too risky to guess |

The check is intentionally narrow:

- `ast.Name` with `id == 'TYPE_CHECKING'`, **or**
- `ast.Attribute` with `attr == 'TYPE_CHECKING'` (any value).

Anything else falls back to `'top'`. False negatives are acceptable
(the import is classified as runtime, which is the safer default for
"must not import" rules); false positives would silently hide runtime
imports from runtime rules and are avoided.

This limitation is documented in the README and glossary.

### Class bodies, conditionals, `try`/`except`

All of these execute at module-load time and are classified as `'top'`:

```python
class Plugin:
    import foo                       # top (rare, but legal)

try:
    import cPickle as pickle         # top
except ImportError:
    import pickle                    # top

if sys.version_info >= (3, 11):
    import tomllib                   # top
else:
    import tomli as tomllib          # top
```

The plugin does **not** model "conditionally executed at runtime"
beyond the `TYPE_CHECKING` special case. Optional-dependency patterns
(`try: import optional except ImportError: optional = None`) read as
top-level imports, which matches how users reason about them: the
project *can* import `optional`, just maybe not on every machine.

### Matching `at=` against placements

Given a user-supplied `at` value, the predicate matches an import iff
its placement is in the expanded set:

| `at=` value                  | Matches placement in …                            |
| ---------------------------- | ------------------------------------------------- |
| `None`                       | `{top, type_checking, function}` (all)            |
| `'top'`                      | `{top}`                                           |
| `'type_checking'`            | `{type_checking}`                                 |
| `'function'`                 | `{function}`                                      |
| `['top', 'function']`        | `{top, function}` (i.e. "not TYPE_CHECKING")      |
| `['top', 'type_checking']`   | `{top, type_checking}` (i.e. "not function")      |

A list is normalized by the factory: the elements are deduplicated and
stored as a `frozenset[Placement]`.

### `external()` matching

`external()` matches an import iff `internal()` would **not** match —
i.e., no prefix of the import's `dot_path` resolves to a known module
in the project tree. By construction, every import the parser sees is
either internal or external; the two targets partition the universe.

Edge: if the parser sees `from . import x` whose resolved path goes
beyond the project root, a warning is logged today and the import is
skipped. That behavior is unchanged — those imports do not exist in
the model, so neither `internal()` nor `external()` sees them.

### Per-predicate behavior

`MustImport` — "at least one matching import exists in scope":
- The `at=` filter is applied alongside `via=` when looking for a
  match. If no import in the scope matches both `path` and `at` (and
  `via`), the predicate reports its usual one-failure-per-`.py`-module
  result. The failure message mentions the placement constraint.

`MustNotImport` — "no matching import exists":
- Filters identically. Each surviving (matching) import is reported as
  one failure, with the placement included in the message.

`MustNotImportPrivate` — "no private imports anywhere":
- `at=` filters the same way; imports outside the requested placement
  are ignored.

### Failure message format

`MustImport` (negative result):

```
[scope <label>] must import <target> at <placement-desc> — no matching import in <file>
```

`MustNotImport`:

```
[scope <label>] must not import <target> at <placement-desc> — found in <file>:<line>
```

`<placement-desc>` rendering:

| `at=`                              | Rendered                              |
| ---------------------------------- | ------------------------------------- |
| `None`                             | omitted (no `at <…>` segment)         |
| `'top'`                            | `top level`                           |
| `'type_checking'`                  | `TYPE_CHECKING block`                 |
| `'function'`                       | `function level`                      |
| list with 2+ entries               | `{<rendered>, <rendered>, …}` (sorted)|

For `MustNotImport` violations, the message also includes the actual
placement of the offending import:

```
[scope myapp.core] must not import any external module at function level
  — found pandas (function level) in src/myapp/core/loader.py:42
```

## Required code changes

### `src/pytest_imports/model.py`

- Add the `Placement` literal at module top:

  ```python
  Placement = Literal['top', 'type_checking', 'function']
  ```

- Extend `ImportInModule`:

  ```python
  @dataclass
  class ImportInModule:
      dot_path: DotPath
      line_no: int
      level: int = 0
      placement: Placement = 'top'
  ```

  Default is `'top'`, matching the most common case.

### `src/pytest_imports/parser.py`

Replace the `ast.walk`-based collector with a recursive descent that
threads the current placement through the tree.

Sketch:

```python
def _collect_imports(
    module_ast: ast.AST,
    node_path: DotPath,
    *,
    placement: Placement = 'top',
) -> Sequence[ImportInModule]:
    imports: list[ImportInModule] = []
    for ast_node in ast.iter_child_nodes(module_ast):
        match ast_node:
            case ast.Import() as ast_import:
                imports.extend(_convert_import(ast_import, placement))
            case ast.ImportFrom() as ast_import_from:
                imports.extend(
                    _convert_import_from(ast_import_from, node_path, placement)
                )
            case ast.FunctionDef() | ast.AsyncFunctionDef() as fn:
                imports.extend(
                    _collect_imports(fn, node_path, placement='function')
                )
            case ast.If() as if_node if (
                placement != 'function' and _is_type_checking(if_node.test)
            ):
                for child in if_node.body:
                    imports.extend(
                        _collect_imports(child, node_path, placement='type_checking')
                    )
                for child in if_node.orelse:
                    imports.extend(
                        _collect_imports(child, node_path, placement=placement)
                    )
            case _:
                imports.extend(
                    _collect_imports(ast_node, node_path, placement=placement)
                )
    return imports


def _is_type_checking(test: ast.expr) -> bool:
    match test:
        case ast.Name(id='TYPE_CHECKING'):
            return True
        case ast.Attribute(attr='TYPE_CHECKING'):
            return True
    return False
```

Extract the existing `ast.Import` and `ast.ImportFrom` body into
`_convert_import` / `_convert_import_from` helpers that take the
current `placement` and set it on the constructed `ImportInModule`.
Keep the relative-import resolution logic unchanged.

### `src/pytest_imports/query.py`

- Add `External` frozen dataclass next to `Internal`. Factory
  `external()`. Extend `Target` union.
- Extend `_match_target` with `case External(): return <not internal>`
  by inlining the existing internal-prefix check (or factoring the
  internal-prefix logic into a small helper used by both arms).
- Add an `at: frozenset[Placement] | None = None` field to
  `MustImport`, `MustNotImport`, and `MustNotImportPrivate` dataclasses.
  Factories accept `at: Placement | list[Placement] | None` and store
  the normalized frozenset:

  ```python
  def _normalize_placements(
      at: Placement | list[Placement] | None,
  ) -> frozenset[Placement] | None:
      if at is None:
          return None
      if isinstance(at, str):
          return frozenset({at})
      return frozenset(at)
  ```

- Plumb the filter through `_find_matching_imports` and
  `_find_matching_private_imports`:

  ```python
  def _find_matching_imports(
      base_node, exclude, target, via, at, root_node,
  ):
      ...
      for import_by in module_node.imports:
          if _match_target(target, import_by.dot_path, root_node) and (
              absolute is None or absolute != bool(import_by.level)
          ) and (at is None or import_by.placement in at):
              yield module_node, import_by
  ```

- Update `_evaluate_predicate` to format `<placement-desc>` and include
  it in failure messages per the table above. Helper:

  ```python
  _PLACEMENT_LABEL = {
      'top': 'top level',
      'type_checking': 'TYPE_CHECKING block',
      'function': 'function level',
  }

  def _format_placement(at: frozenset[Placement] | None) -> str | None:
      if at is None:
          return None
      if len(at) == 1:
          return _PLACEMENT_LABEL[next(iter(at))]
      return '{' + ', '.join(sorted(_PLACEMENT_LABEL[p] for p in at)) + '}'
  ```

- For `MustNotImport`, also format the actual placement of the
  offending import (always rendered via `_PLACEMENT_LABEL`).

### `src/pytest_imports/__init__.py`

Export `external` and add to `__all__`.

`Placement` is an implementation detail; do not export by default but
keep it accessible via `from pytest_imports.model import Placement` for
advanced users (e.g. custom helpers).

### `src/pytest_imports/plugin.py`

No changes — `ImportsFixture.check()` is predicate-agnostic.

## Tests

### `test/unit/test_parser.py`

Add coverage for every placement and every priority rule:

- Module-top `import foo` → `placement='top'`.
- `try: import foo` at module top → `'top'`.
- Inside a class body → `'top'`.
- Inside `if TYPE_CHECKING:` (both `Name` and `Attribute` forms) →
  `'type_checking'`.
- Inside an `else:` of a `TYPE_CHECKING` if → reverts to surrounding.
- Inside nested `if TYPE_CHECKING:` → still `'type_checking'`.
- Inside `def`, `async def`, method, nested function → `'function'`.
- Inside `if TYPE_CHECKING:` *inside* a `def` → `'function'` (function
  wins).
- Aliased `TYPE_CHECKING` (`from typing import TYPE_CHECKING as TC; if TC:`)
  → `'top'` (documented limitation).
- `if not TYPE_CHECKING:` → `'top'`.

### `test/unit/test_query.py`

For each predicate (`must_import`, `must_not_import`,
`must_not_import_private`):

- `at=None` (default) matches all placements (existing tests stay
  green).
- `at='top'` matches only `top`, not `type_checking` or `function`.
- `at='type_checking'` matches only TYPE_CHECKING.
- `at='function'` matches only function-level.
- `at=['top', 'function']` matches both, excludes TYPE_CHECKING.
- `at=['top', 'type_checking']` matches both, excludes function-level.

`external()` target:

- Resolves to imports outside the source roots; stdlib (`os`, `sys`),
  third-party fixtures, anything not in the model.
- `internal()` and `external()` produce a partition: for any module
  with imports of both kinds, running each rule independently covers
  every import exactly once.
- `must_not_import(external())` inside `scope('myapp.core')` flags
  third-party imports but not internal ones, and vice versa.
- Relative imports resolved within the model are internal, not
  external.

Failure-message formatting:

- `MustImport` with `at='function'` and no match: message ends with
  `at function level`.
- `MustNotImport` with `at='top'` and a violation: message ends with
  `at top level — found <name> (<actual placement>) in <file>:<line>`.

### `test/integration/`

A small sample tree exercising the cross-axis combinations:

```
sample/
  pkg/
    __init__.py        # import os  (top, external)
    bootstrap.py       # if TYPE_CHECKING: from .types import T
                       # import pandas  (top, external)
                       # def go(): from .heavy import H  (function, internal)
    types.py
    heavy.py
```

Rules:

- `project(): must_not_import(external(), at='function')` — no
  violations (the only function-level import is internal).
- `project(): must_not_import(internal(), at='function')` — one
  violation: `bootstrap.go` lazy-imports `.heavy`.
- `'pkg.bootstrap': must_import('pkg.types', at='type_checking')` — OK.
- `'pkg.bootstrap': must_not_import('pandas', at='top')` — one
  violation at the top-level `import pandas`.

### `test/arch/`

If a natural rule exists for the plugin itself, add one. Candidate:
`project(): must_not_import(external(), at='function')` — the plugin
should not lazy-import third-party packages. Skip if it produces
false-flag noise on standard-library lazy imports.

## Docs

### `README.md`

- Add quick-reference rows:
  - `` `at='top' / 'type_checking' / 'function'` `` — option —
    Restrict a predicate to imports at a given placement.
  - `` `external()` `` — target — Match any import resolving outside
    the configured source roots.
- Add a new example section between the `via=` example and the
  `descendants` example, showing both a `must_not_import(... at='function')`
  rule and the `external()` symmetry. Brief paragraph on the three
  placements, the rule that function-level beats TYPE_CHECKING, and the
  documented limitation that aliased `TYPE_CHECKING` is not recognized.

### `AGENTS.md`

- Update the `model.py` and `parser.py` bullets under **Data flow** to
  mention the placement field and the recursive AST traversal.
- Update the `query.py` bullet to list the `at=` option and the new
  `External` target.
- Under **Key internals**, add: placement classification is one-way
  (function-level overrides TYPE_CHECKING); `TYPE_CHECKING` recognition
  is AST-shape based and intentionally narrow.

### `GLOSSARY.md`

Add entries under **Imports**:

- **top-level import** — A statement at the module's top level (not
  nested in any `def` or `async def`) and not inside a recognized
  `if TYPE_CHECKING:` block. This includes class bodies, `try`/`except`,
  and other conditional constructs that execute at module load time.
  In our model this is the `'top'` placement.
- **type-checking import** — A top-level import inside the `body` of a
  recognized `if TYPE_CHECKING:` block, executed only by static type
  checkers, not at runtime. In our model this is the `'type_checking'`
  placement.
- **function-level import** — An import nested inside a `def` or
  `async def` body, at any depth. Also called a *lazy import*. In our
  model this is the `'function'` placement. Function-level beats
  TYPE_CHECKING: an import inside `if TYPE_CHECKING:` inside a function
  body is still `'function'`.

The existing **external import** entry already exists; cross-link the
new `external()` target from it.

## Open questions / non-goals

- **More conditional placements** beyond `TYPE_CHECKING` (e.g.
  `top_conditional` for `try: import optional`, `top_version_gated`
  for `if sys.version_info ...`, `top_platform_gated` for
  `if sys.platform == ...`) are out of scope. TYPE_CHECKING earns its
  slot because it changes runtime semantics (never executes) and has a
  unique easy-to-pattern-match AST shape; every other conditional
  construct executes on at least one runtime code path and the
  conditions are arbitrary expressions with no clean partition. Most of
  those distinctions are better made on the **target** axis (forbid
  importing `winreg` by name, forbid the specific optional dep). If
  real demand emerges for a "wrapped in any conditional" signal, the
  cleanest extension is an **orthogonal** axis (e.g. a `when=` option
  or a `conditional: bool` field), not more `at=` literals.
- **Recognizing aliased `TYPE_CHECKING`** (`from typing import TYPE_CHECKING as TC`)
  requires tracking name bindings in the module — meaningful additional
  complexity in the parser. Documented limitation; revisit if it bites.
- **`stdlib()` and `third_party()` targets** as a refinement of
  `external()` are out of scope. Distinguishing them requires knowing
  the stdlib module list per Python version (`sys.stdlib_module_names`)
  and/or installed package metadata; both are doable but unmotivated
  until there is a real use case.
- **`must_not_import_private(external())`** — generalizing
  `must_not_import_private` to take a `Target` instead of `str | None`
  is an independent change. Track separately; this spec keeps the
  existing signature and only adds `at=`.
- **`at=` on `must_only_import`** — if the `must_only_import` spec
  lands, it should accept `at=` with the same semantics. Mention in
  that spec; do not pre-build here.
- **Nested-function granularity** (distinguishing "lazy import inside a
  module-level function" from "lazy import inside a closure inside a
  method") is out of scope. Both are `function`.
- **Reporting placement counts** as part of `MustImport` success (e.g.
  "found 3 top-level imports of X, 1 function-level") is out of scope;
  predicates report violations only.
- **Naming**: `at=` was chosen over `where=`, `placement=`, `level=`,
  and `lazy=True/False` for terseness and parity with the existing
  `via=` option. The three primitive literals (`'top'`,
  `'type_checking'`, `'function'`) are kept flat — no union alias —
  because their default reading then matches user intent (see resolved
  open question above).
