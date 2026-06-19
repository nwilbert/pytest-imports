# Spec: `must_only_import` + target ergonomics

This spec bundles four related improvements that all came out of writing
realistic architecture rules against Django. They share a theme —
making the *target* side of the rule API as expressive as the *scope*
side — and their implementations touch overlapping code paths
(`_match_target`, `_find_matching_imports`, predicate dataclasses, the
`Target` union, the `Predicate` union).

1. **`must_only_import` predicate** — allowlist complement of
   `must_not_import`. The headline change; Part 1 below.
2. **List-of-targets** accepted by `must_import`, `must_not_import`,
   and (once Part 4 lands) `must_not_import_private`. Removes the most
   common boilerplate — "forbid each of these". Part 2 below.
3. **`descendants(path, without=...)`** — target-side `without=`
   mirror of `scope(path, without=...)`, so "descendants of X except Y"
   becomes expressible. Part 3 below.
4. **`must_not_import_private` accepts `Target`** — aligns with the
   other target-accepting predicates so `internal()` and
   `descendants(...)` work as filters too. Part 4 below.

Cross-references between the parts are noted where the design
interacts — most importantly, `must_only_import` is meaningfully more
expressive once Part 3 lands, because the canonical "allow contrib
except admin" rule becomes one predicate
(`must_only_import([descendants('django.contrib', without='admin')])`).

A consolidated **Open questions / non-goals** section follows at the
end and covers all four parts.

---

## Part 1 — `must_only_import` predicate

### Motivation

`must_not_import` is a denylist: "this scope must not import these
targets." Denylists work well when there are a few forbidden things and
many permitted ones, but they invert badly for layered architectures
where the natural statement is "this layer may only import from these
few places." Writing the denylist for that case requires enumerating
every other internal package and keeping the list in sync as the project
grows.

`must_only_import` provides the allowlist complement: "within a bounded
universe of imports, only these targets are permitted." Anything inside
the universe that is not in the allowlist is a violation; anything
outside the universe is ignored.

The common case is restricting internal imports while leaving stdlib and
third-party imports untouched — e.g. `myapp.api` may only reach into
`myapp.core` and `myapp.schemas`, but may freely import `typing`,
`fastapi`, `pydantic`, etc. To keep that case clean without baking
`_internal` into the predicate name, the universe is a second parameter
`among`, defaulting to `internal()`.

### Public API

```python
from pytest_imports import must_only_import, scope, descendants

def test_api_layer_imports(imports):
    imports.check({
        scope('myapp.api'): must_only_import(['myapp.core', 'myapp.schemas']),
    })

def test_capture_subtree_self_contained(imports):
    imports.check({
        scope('myapp.capture'):
            must_only_import(
                descendants('myapp.capture'),
                among=descendants('myapp'),
            ),
    })
```

Signature:

```python
def must_only_import(
    allowed: Target | list[Target],
    *,
    among: Target = Internal(),
    via: Via | None = None,
) -> MustOnlyImport: ...
```

Predicate dataclass:

```python
@dataclass(frozen=True)
class MustOnlyImport:
    allowed: tuple[Target, ...]
    among: Target = Internal()
    via: Via | None = None
```

Added to the `Predicate` union in `query.py`.

`Internal()` is safe as a default value because it is a frozen
dataclass with no fields — every instance compares equal. A single
`Target` passed to `allowed` is normalized to a one-element tuple by the
factory.

Implementation note: under the step-down ordering, the factory
functions precede the `Internal` class, so `among=Internal()` cannot be
a literal factory default (it would name `Internal` before it exists).
The implemented factory uses `among: Target | None = None` and
delegates to the dataclass field default `among: Target = Internal()`,
keeping a single source of truth for the default. The `MustOnlyImport`
dataclass therefore carries the `Internal()` default on its `among`
field (it is defined after `Internal`).

### Semantics

For each module in scope and each of its imports:

1. If the import's `dot_path` does not match `among` (per the existing
   `_match_target` logic), skip it — it is outside the universe.
2. If the import does not satisfy `via` (when `via` is set), skip it.
3. If the import's `dot_path` matches **any** entry in `allowed`, it is
   permitted.
4. Otherwise, it is a violation.

"Matches" reuses `_match_target`: a string entry matches the path and
its descendants; `descendants(p)` matches strict descendants;
`internal()` matches anything internal. A `MustOnlyImport` with
`internal()` in `allowed` and `among=internal()` is vacuous but allowed
— no need to special-case.

Each violating import line produces one failure (mirrors
`MustNotImport`).

#### Examples

Given `must_only_import(['myapp.core', 'myapp.schemas'])` (defaults:
`among=internal()`, `via=None`), applied to `myapp.api.routes`:

| Import statement                       | Result    | Reason                                  |
| -------------------------------------- | --------- | --------------------------------------- |
| `from myapp.core import service`       | OK        | matches `'myapp.core'`                  |
| `from myapp.core.detail import X`      | OK        | descendant of `'myapp.core'`            |
| `from myapp.schemas import User`       | OK        | matches `'myapp.schemas'`               |
| `from myapp.persistence import db`     | violation | internal, not in allowed                |
| `import myapp.other`                   | violation | internal, not in allowed                |
| `import os`                            | OK        | outside `among=internal()`              |
| `from fastapi import APIRouter`        | OK        | outside `among=internal()`              |
| `from . import helpers` (rel.)         | depends   | resolved absolute path is checked       |

The last row: relative imports are evaluated against their resolved
absolute `dot_path`, same as for `MustNotImport`. So
`from . import helpers` inside `myapp.api.routes` resolves to
`myapp.api.helpers`, which is internal but not in the allowlist →
violation.

#### Empty allowlist

`must_only_import([])` is permitted and means "no imports allowed
within `among`". With `among=internal()` this is equivalent to
`must_not_import(internal())`. Useful as a guardrail for a leaf module
that must not reach back into the project.

#### Self-imports inside the scope

Imports of modules **inside the current scope** are not implicitly
allowed. If a user wants a scope's internal cohesion to be exempt, they
list the scope path explicitly:

```python
scope('myapp.capture'):
    must_only_import(['myapp.capture', 'myapp.core'])
```

This is intentional. Implicit self-allow would conflate scope (the
modules a rule applies *to*) with target (the modules it may *reach*),
and would make the semantics depend on `scope` in surprising ways.

#### Failure message format

Default case (non-empty allowlist):

```
  [scope <label>] must only import {<a>, <b>, …} among <among>
    — found <actual> in <file>:<line>
```

Empty-allowlist special case:

```
  [scope <label>] must not import anything among <among> — found <actual> in <file>:<line>
```

(Phrased `anything among <among>` rather than `any <among>` so it reads
correctly when `_format_target(among)` already begins with "any" — e.g.
`among=internal()` renders "any internal module".)

`<among>` uses the existing `_format_target` rendering: `internal()` →
`"any internal module"`, a string → the string, `descendants(p)` →
`"descendants of <p>"`.

`<a>, <b>, …` are produced by mapping `_format_target` over `allowed`
and joining with `, ` inside braces.

### Required code changes

#### `src/pytest_imports/query.py`

- Add `MustOnlyImport` frozen dataclass (fields above).
- Add factory `must_only_import`:
  - Normalize single `Target` to a one-element list.
  - Convert list to `tuple` for hashability.
  - Set `among` default to `Internal()`.
- Extend the `Predicate` union to include `MustOnlyImport`.
- Add a `case MustOnlyImport():` arm in `_evaluate_predicate`. Logic:

  ```python
  case MustOnlyImport():
      among_str = _format_target(predicate.among)
      allowed_str = (
          '{' + ', '.join(_format_target(t) for t in predicate.allowed) + '}'
      )
      for module_node, import_by in _find_matching_imports(
          node, exclude, predicate.among, predicate.via, root_node
      ):
          if any(
              _match_target(t, import_by.dot_path, root_node)
              for t in predicate.allowed
          ):
              continue
          location = f'{module_node.file_path}:{import_by.line_no}'
          if predicate.allowed:
              failures.append(
                  f'  [scope {scope_label}] must only import {allowed_str}'
                  f' among {among_str} — found {import_by.dot_path}'
                  f' in {location}'
              )
          else:
              failures.append(
                  f'  [scope {scope_label}] must not import anything'
                  f' among {among_str} — found {import_by.dot_path}'
                  f' in {location}'
              )
  ```

  Note this reuses `_find_matching_imports` to filter by `among` and
  `via`, then applies the allowlist check inline. No new helper is
  needed — the existing iterator already does the universe walk.

#### `src/pytest_imports/__init__.py`

Export `must_only_import` and add to `__all__`.

#### No changes needed in

- `model.py` — `MustOnlyImport` reads existing `ImportInModule` fields.
- `parser.py` — no new AST information required.
- `plugin.py` — `ImportsFixture.check()` and `.violations()` are
  predicate-agnostic.

### Tests

#### `test/unit/test_query.py`

- One test per row of the semantics table above.
- Single-target form: `must_only_import('myapp.core')` accepts the
  string as a one-element list.
- `descendants` in `allowed`: `must_only_import(descendants('myapp.core'))`
  permits `myapp.core.sub` but flags a bare `import myapp.core`.
- `among=descendants('myapp')`: a scope inside `myapp.capture` may
  import any `myapp.capture.*` (listed via `descendants('myapp.capture')`
  in `allowed`) but is flagged for `from myapp.persistence import x`.
  Stdlib and third-party imports inside the same scope are not flagged.
- `via='relative'`: the rule only flags relative imports that fall
  outside the allowlist; absolute imports are ignored.
- Empty `allowed`: every internal import in scope produces a failure;
  external imports do not.
- Multiple violations in one module produce one failure per violating
  line.
- Multiple `Target` types mixed in `allowed`: `['myapp.core',
  descendants('myapp.schemas')]` — verify both forms match.
- Interaction with `scope(..., without=...)`: excluded submodules are
  not walked, so their disallowed imports do not produce failures.
- Vacuous case: `must_only_import(internal())` with the default
  `among=internal()` produces no failures regardless of imports.

#### `test/integration/`

A small sample tree exercising the layered-architecture use case in the
motivation: an `api` package allowed to import `core` and `schemas` but
not `persistence`. Verify exact failure messages.

#### `test/arch/`

Add a self-referential rule for `pytest_imports` itself if a natural
allowlist exists for one of the internal modules (e.g. `query.py` may
only import from `model`). Optional — skip if no such layering applies.

### Docs

#### `README.md`

- Add a new row to the quick-reference table:
  ``| `must_only_import(allowed, among=internal())` | predicate | Allow only the listed targets within `among`; anything else inside `among` is a violation. |``
- Add a new example section between `must_not_import` and the
  `descendants` example. Use the layered-architecture case from the
  motivation. Explain the `among` default and when to override it.

#### `AGENTS.md`

- Update the `query.py` bullet under **Data flow** to list
  `MustOnlyImport` alongside the existing predicates.
- Update the **Key internals** list to note: `MustOnlyImport` walks the
  same iterator as `MustNotImport` (filtered by `among`) and applies
  the allowlist check inline; one failure per violating import line.

#### `GLOSSARY.md`

No new terms — `allowlist`, `among`, `allowed`, and `universe` are
ordinary English used descriptively, not domain terms. If future
predicates also take an `among`-style parameter, revisit and possibly
add a *universe* entry.

---

## Part 2 — list-of-targets for `must_import` / `must_not_import` / `must_not_import_private`

### Motivation

The most repetitive shape in the Django benchmark was a fan-out of
identical predicates over a list of forbidden targets:

```python
scope('django.utils'): [
    must_not_import('django.db'),
    must_not_import('django.template'),
    must_not_import('django.forms'),
    must_not_import('django.views'),
    must_not_import('django.urls'),
    must_not_import('django.contrib'),
]
```

The rule dict already lets you supply `list[Predicate]` per scope, so
the cost is purely a per-predicate factory call. Letting the factories
accept `Target | list[Target]` directly compresses this to a single
predicate — both for ergonomics and so the failure message can name the
specific target that matched.

`must_only_import` already accepts a list for `allowed`. This part
extends the same convention to the other predicates so the API is
uniform.

### Public API

```python
def must_import(
    path: Target | list[Target], *, via: Via | None = None
) -> MustImport: ...

def must_not_import(
    path: Target | list[Target], *, via: Via | None = None
) -> MustNotImport: ...

def must_not_import_private(
    path: Target | list[Target] | None = None,
) -> MustNotImportPrivate: ...
```

A single `Target` is normalized to a one-element tuple by the factory.
`None` for `must_not_import_private` is preserved as "no filter — flag
all private imports."

Dataclass fields become tuples:

```python
@dataclass(frozen=True)
class MustImport:
    path: tuple[Target, ...]
    via: Via | None = None

@dataclass(frozen=True)
class MustNotImport:
    path: tuple[Target, ...]
    via: Via | None = None

@dataclass(frozen=True)
class MustNotImportPrivate:
    path: tuple[Target, ...]  # empty tuple = no filter
```

(Field renames optional — keeping `path` for continuity is fine even
though the value is now a tuple of targets.)

### Semantics

The semantics chosen per predicate reflect what each rule *means* when
read aloud — and match what you would get if you expanded the list into
N separate predicates of the same type:

- **`must_import([t₁, …, tₙ])`** — **AND** over targets. The scope must
  contain a matching import for *each* target. Equivalent to N
  independent `must_import` predicates. Each unsatisfied target yields
  one failure for the scope (matching the current per-rule reporting
  from `MustImport` — the message `— no matching import found`, one per
  unsatisfied target).
- **`must_not_import([t₁, …, tₙ])`** — **OR** per import. An import is
  a violation if it matches *any* listed target. Each violating import
  line yields one failure. The failure message names the predicate's
  target set (see *Failure message* below).
- **`must_not_import_private([t₁, …, tₙ])`** — **OR** per import. A
  private import is flagged if it matches *any* listed filter target.
  The empty tuple keeps today's "no filter — any private import is
  flagged" semantic. (This part depends on Part 4: `must_not_import_private`
  must first accept `Target` before `list[Target]` is meaningful.)

The AND/OR asymmetry is the right one: `must_X` reads "all of these
must hold," `must_not_X` reads "none of these may hold." The semantics
match what users mean and what the list-of-predicates aggregator already
produces.

### Failure message format

Single-target form:

```
  [scope <label>] must not import <t> — found <actual> in <file>:<line>
```

This **unifies** the current message. Today `_evaluate_predicate`
branches on the target kind (`isinstance(predicate.path, str)`): a
string target emits `— found in <file>` with no `<actual>`, while a
structured target emits `— found <actual> in <file>`. That asymmetry
loses information for a string target that matches a *descendant* — e.g.
`must_not_import('a.b')` tripped by an import of `a.b.c` reports only
`must not import a.b — found in …`, never naming `a.b.c`. Part 2 drops
the branch and always includes `<actual>`. The only cost is mild
redundancy when the import exactly equals a string target
(`— found a.b in …`), which is acceptable and arguably clearer. This is
a deliberate, behavioral change to the existing single-target output;
update the affected tests accordingly.

Multi-target form (new):

```
  [scope <label>] must not import {<t₁>, <t₂>, …} — found <actual>
    matching <t_k> in <file>:<line>
```

`<t_k>` is the specific listed target that matched, so the message
points the reader at the rule entry to inspect. Targets are rendered via
`_format_target`. For `must_import` (AND semantics) the existing
`— no matching import found` message is reused, one failure per
unsatisfied target.

### Required code changes

#### `src/pytest_imports/query.py`

- Update `must_import`, `must_not_import`, `must_not_import_private`
  factory functions to normalize `Target | list[Target]` (and `None`
  for the private factory) to `tuple[Target, ...]`.
- Update dataclass fields to `tuple[Target, ...]`.
- Update the `case MustImport():` / `case MustNotImport():` /
  `case MustNotImportPrivate():` arms in `_evaluate_predicate`:
  - `MustImport`: outer loop over targets, inner reuse of
    `_find_matching_imports` per target.
  - `MustNotImport`: single walk over imports, OR-match against the
    tuple, record the matched target in the failure for reporting. Drop
    the existing `isinstance(predicate.path, str)` branch — both string
    and structured targets now render `<actual>` (see *Failure message
    format* above).
  - `MustNotImportPrivate`: extend `_find_matching_private_imports` to
    take `tuple[Target, ...]` and OR-match against it.

#### `src/pytest_imports/__init__.py`

No new exports — same factory names.

#### No changes needed in

- `model.py`, `parser.py`, `plugin.py` — the multi-target lift is
  internal to `query.py`.

### Tests

#### `test/unit/test_query.py`

- `must_import('a')` and `must_import(['a'])` produce equivalent
  predicates (single-target normalization).
- `must_import(['a', 'b'])` reports one failure per missing target
  per file — verify AND semantics.
- `must_not_import(['a', 'b'])` flags imports of `a`, `a.sub`, `b`,
  and ignores imports of `c`. Failure message includes the matching
  target.
- `must_not_import([])` (vacuously) produces no failures.
- `must_not_import([Descendants('a'), 'b'])` mixes target shapes.
- `must_not_import_private([…])` once Part 4 lands; see Part 4 tests.

#### `test/integration/`

A small sample tree verifying the failure-message format for the
multi-target form.

### Docs

#### `README.md`

- Update the layered example (`test_layered_architecture`) to use the
  list form, demonstrating the saved boilerplate.
- Add a one-line note to the quick-reference table cells for
  `must_import` and `must_not_import` saying they accept a list of
  targets.

#### `AGENTS.md`

- Update the **Data flow** bullet for `query.py` to mention that
  `MustImport.path` / `MustNotImport.path` /
  `MustNotImportPrivate.path` are tuples of targets (empty = no
  filter, for the private case).

#### `GLOSSARY.md`

No new terms.

---

## Part 3 — `descendants(path, without=...)`

### Motivation

`scope(path, without=...)` lets the scope side carve out specific
subtrees. There is no symmetric construct on the target side. To express
"anything under `django.contrib` except `django.contrib.admin`" today,
you have to enumerate the rest of contrib as a long list of
`must_not_import` predicates. Adding a new contrib subpackage silently
invalidates the rule.

A target-side `without=` closes the gap. The motivating use is inside
`must_only_import`: "allow descendants of `django.contrib`, except
descendants of `django.contrib.gis`."

### Public API

```python
def descendants(
    path: str, *, without: str | list[str] | None = None
) -> Descendants: ...

@dataclass(frozen=True)
class Descendants:
    path: str
    without: tuple[str, ...] = ()
```

`without` accepts the same shapes as `scope(without=...)`: a single
string, a list of strings, dotted nested paths.

### Semantics

`Descendants(path, without)` matches a `dot_path` iff:

1. `dot_path` is a **strict** descendant of `path` (existing
   semantics — `dot_path == path` does not match), **and**
2. For each `w` in `without`, `dot_path` is **not** equal to and
   **not** a descendant of `DotPath(path) / DotPath(w)`.

`without=()` (default, no carve-outs) reproduces today's behavior
exactly.

`without` is interpreted relative to `path`, not absolute. So
`descendants('django.contrib', without='admin')` excludes the
`django.contrib.admin` subtree.

#### Failure message format

`_format_target(Descendants(path, without))` renders:

- `descendants of <path>` when `without` is empty (unchanged).
- `descendants of <path> except {<w₁>, <w₂>, …}` when non-empty.

### Required code changes

#### `src/pytest_imports/query.py`

- Update `descendants` factory to accept `without` and normalize it
  (single string → one-element list, list → tuple).
- Add `without: tuple[str, ...] = ()` field to `Descendants`.
- Extend the `case Descendants(...)` arm in `_match_target` to filter
  out paths under any excluded subtree.
- Extend `_format_target` for the new render case.

#### `src/pytest_imports/__init__.py`

No new exports — same factory name.

#### No changes needed in

- `model.py`, `parser.py`, `plugin.py`.

### Tests

#### `test/unit/test_query.py`

- `descendants('a', without='b')` matches `a.c`, not `a.b`, not
  `a.b.c`.
- `descendants('a', without=['b', 'd'])` matches `a.c` only.
- `descendants('a', without='b.x')` matches `a.b.y`, but not `a.b.x`
  and not `a.b.x.z` (nested-path exclusion).
- Bare `descendants('a')` still matches all strict descendants (no
  regression).
- `_format_target(descendants('a', without='b'))` renders correctly.

#### `test/integration/`

One end-to-end test that uses `must_not_import(descendants('django.contrib',
without='admin'))` against a small fixture tree.

### Docs

#### `README.md`

- Update the `descendants` quick-reference row to mention the
  `without=` keyword and link to the relevant example.
- Add a paragraph under the existing `descendants` example showing
  the `without=` form alongside.

#### `AGENTS.md`

- Update the **Key internals** list to mention that `Descendants` may
  carry `without` exclusions, evaluated in `_match_target`.

#### `GLOSSARY.md`

No new terms.

---

## Part 4 — `must_not_import_private` accepts `Target`

### Motivation

`must_not_import_private(path: str | None)` is the only
target-accepting predicate that takes a raw string instead of a
`Target`. That blocks rules like:

- `must_not_import_private(internal())` — "no private imports of
  anything inside the project." Today's API can only express this by
  scoping the rule to the project externally; the filter-by-target is
  the natural way.
- `must_not_import_private(descendants('myapp.capture'))` — "no
  private imports of capture internals, but `myapp.capture._public`
  itself (if it existed) would not be flagged."

Aligning this predicate with the `Target` family removes a small but
real inconsistency and is a prerequisite for Part 2's
`must_not_import_private(list[Target])`.

### Public API

```python
def must_not_import_private(
    path: Target | list[Target] | None = None,
) -> MustNotImportPrivate: ...

@dataclass(frozen=True)
class MustNotImportPrivate:
    path: tuple[Target, ...]  # empty tuple = no filter
```

Backwards compatibility: `must_not_import_private('myapp')` still
works; the string is normalized to a one-element tuple, and a string
`Target` already matches `'myapp'` and its descendants under the
existing `_match_target` rules.

### Semantics

A private import is flagged iff:

1. Its `dot_path` contains a private name part (existing semantics —
   any part starting with `_`, except `__future__`), **and**
2. Either `path` is empty (no filter) **or** the import's `dot_path`
   matches at least one target in `path` (per `_match_target`).

This generalizes today's "is_relative_to filter_path" check uniformly:
the previous behavior is the special case where `path` is a single
string target.

### Required code changes

#### `src/pytest_imports/query.py`

- Update `must_not_import_private` factory: accept
  `Target | list[Target] | None`, normalize to `tuple[Target, ...]`
  (empty tuple for `None`).
- Update `MustNotImportPrivate.path` field type to `tuple[Target, ...]`.
- Update `_find_matching_private_imports` signature: replace the
  `path: str | None` parameter with `path: tuple[Target, ...]`, and
  swap the `is_relative_to` check for an OR-match across the tuple via
  `_match_target`.
- Update the `case MustNotImportPrivate():` arm in
  `_evaluate_predicate` to pass the tuple through and render the
  failure message in the multi-target style (or fall back to the
  single-target rendering when len == 1, for continuity).

#### `src/pytest_imports/__init__.py`

No new exports.

#### No changes needed in

- `model.py`, `parser.py`, `plugin.py`.

### Tests

#### `test/unit/test_query.py`

- `must_not_import_private()` (no filter) — unchanged behavior; all
  private imports flagged.
- `must_not_import_private('myapp')` — unchanged behavior; only
  private imports under `myapp` flagged.
- `must_not_import_private(internal())` — flags
  `from myapp._x import y`, ignores `from external._x import y` when
  `external` is not in the model.
- `must_not_import_private(descendants('myapp.capture'))` — flags
  `from myapp.capture._x import y` (resolves to `myapp.capture._x.y`,
  under the subtree), ignores a private import outside the subtree such
  as `from myapp._secret import z`. Note that `from myapp.capture
  import _y` resolves to `myapp.capture._y`, which *is* a strict
  descendant of `myapp.capture`, so it is flagged too — the parser
  records the imported name as the last path part, so `descendants`
  only excludes a bare `import myapp.capture` (which carries no private
  part anyway).
- `must_not_import_private([t₁, t₂])` — flags imports matching
  either filter.

#### `test/integration/`

A small tree showing `must_not_import_private(internal())` in
practice.

### Docs

#### `README.md`

- Update the `must_not_import_private` example and quick-reference row
  to show the `Target` form and mention `internal()` and
  `descendants(...)` as valid filters.

#### `AGENTS.md`

- Update the `query.py` **Key internals** bullet to note that
  `MustNotImportPrivate` now uses the `_match_target` filter family
  rather than `is_relative_to`.

#### `GLOSSARY.md`

No new terms.

---

## Open questions / non-goals

Spanning all four parts:

- **Unbounded universe** for `must_only_import` (`among=None` meaning
  "any import"). Out of scope. The predicate is designed for *bounded*
  allowlists; for stdlib + third-party constraints, layer multiple
  `must_only_import` rules with narrower `among` values, or use
  `must_not_import` for the denylist case. Can be added later as
  `among: Target | None = Internal()` with a small branch in
  evaluation.
- **`exclude=` on `must_only_import`** ("only these, except for those
  descendants"). Largely covered by Part 3: write
  `must_only_import([descendants('a', without='b')])`. A dedicated
  `exclude=` parameter would be additive sugar; revisit if real use
  cases appear.
- **Implicit self-allow** for `must_only_import` (scope's own
  descendants always allowed). Rejected for the reason in *Self-imports
  inside the scope* under Part 1.
- **Reporting outside-the-universe imports** (info-level diagnostics
  for skipped imports). Out of scope; predicates report only
  violations.
- **Multiple `among` universes per rule** (`among=[internal(), 'numpy']`).
  Out of scope; one universe per rule. If needed, write two rules.
- **`must_only_import` naming**: chosen over `may_only_import`,
  `restrict_imports`, `imports_limited_to`, and `must_not_import(...,
  except_for=...)` to keep the `must_*` family consistent. The `among=`
  parameter avoids the awkward `must_only_import_internal` naming.
- **`without=` on a string target** (`'a.b'` with a `without=` carve-out).
  Out of scope. The string target shape is intentionally minimal; if a
  user needs exclusions, they should write
  `descendants('a.b', without=…)`. (String targets match the path
  itself; `descendants` is the natural place for subtree carve-outs.)
- **`without=` on `internal()`**. Out of scope. `internal()` is a
  binary universe filter and is rarely the right place to express
  carve-outs; the same effect can be achieved by scoping or by
  combining `internal()` with a `must_not_import(descendants('X'))` on
  the side.
- **Multi-target `must_import` with OR semantics** ("at least one of
  these must be imported somewhere in scope"). Out of scope. The AND
  semantics in Part 2 follow the natural reading and the existing
  list-of-predicates expansion. If an OR variant turns out to matter,
  add `must_import_any(...)` rather than overloading `must_import`.
- **Layered-architecture sugar** (e.g. a `layered(['utils', 'db',
  'template', 'forms']).strict()` helper). Out of scope here; tracked
  as a separate spec because it composes on top of these primitives
  rather than extending them.
