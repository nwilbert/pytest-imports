# Spec: `layered` rule-dict helper

A small, pure-Python helper that builds a strict N-tier layering as a
rule dict over the primitives. Sized as a follow-on to
[`must_only_import.md`](../must_only_import.md); add this after that
spec lands.

## Prerequisites

This spec assumes:

- **Part 1 of `must_only_import.md`** — the `must_only_import`
  predicate with `among: Target = Internal()`.

`descendants(path, without=...)` (Part 3) and multi-target predicates
(Part 2) from that spec are *not* required for `layered` to work.

## Motivation

With `must_only_import` in place, a strict N-tier layering inside a
package is expressed as N parallel `must_only_import` rules whose
allowlists are the triangular prefix of the layer list:

```python
imports.check({
    scope('myapp.utils'):    must_only_import([]),
    scope('myapp.db'):       must_only_import(['myapp.utils']),
    scope('myapp.template'): must_only_import(['myapp.utils', 'myapp.db']),
    scope('myapp.forms'):    must_only_import(['myapp.utils', 'myapp.db', 'myapp.template']),
})
```

That is already correct and readable. The remaining costs are:

1. **The triangular prefix is mechanical and error-prone.** Writing
   layer 3's allowlist by hand and forgetting `'myapp.db'` is a silent
   bug — the rule still passes for imports that wouldn't have been
   flagged anyway.
2. **Inserting a layer in the middle requires editing every higher
   layer's allowlist** to include the new name. A one-list change
   becomes a multi-line edit.
3. **The structural fact "this is one layered architecture"** is
   distributed across N independent rules; a maintainer can change one
   in isolation and silently break the layering invariant.

A small helper that takes the layer list once and produces the rule
dict closes all three. It is **pure desugaring** — no new predicate,
no new evaluator code path, no new failure-message format.

## Public API

```python
from pytest_imports import layered

def test_layering(imports):
    imports.check(layered('myapp', ['utils', 'db', 'template', 'forms']))
```

Signature:

```python
def layered(base: str, layers: Sequence[str]) -> dict[Scope, MustOnlyImport]:
    ...
```

Returns a `dict[Scope, MustOnlyImport]` that can be passed straight to
`imports.check` (or `imports.violations`), or merged with hand-written
rules via `**`:

```python
imports.check({
    **layered('myapp', ['utils', 'db', 'template']),
    scope('myapp.api'): must_only_import(['myapp.db', 'myapp.schemas']),
})
```

Dict-merge on key collision lets the caller override a specific layer's
rule by listing it explicitly after the spread — useful for the
occasional layer that needs a wider allowlist than the strict layering
permits, without forking the helper.

## Semantics

For layers `[L₀, L₁, …, L_{n-1}]` rooted at `base`, the returned dict
contains, for each `i`:

```python
scope(f'{base}.{L_i}'): must_only_import(
    [f'{base}.{L_j}' for j in range(i)],
    among=descendants(base),
)
```

So:

- `L₀` is forbidden from importing any other named layer (allowlist
  empty).
- `L_i` may import descendants of `L_0, …, L_{i-1}`. It may import
  within its own scope (its own scope is not in `among`'s universe —
  see below).
- Imports of `base` itself (e.g. `myapp/__init__.py`) are outside
  `among=descendants(base)` and are not constrained.
- Imports outside `base` (stdlib, third-party, sibling packages) are
  outside the universe and unconstrained.

`among=descendants(base)` is set explicitly by the helper rather than
relying on the `internal()` default. Reasoning: the helper *knows* the
user named a subtree; if their project happens to have sibling
packages under the source root, those siblings should not be
accidentally constrained by a rule the user intended for `base`. For
the canonical case where `base` *is* the project, this matches what
the `internal()` default would do anyway.

### Edge cases

- **Empty layer list** (`layered('myapp', [])`) returns `{}`. Composes
  cleanly with `**`; no failure ever produced.
- **Single layer** (`layered('myapp', ['utils'])`) returns one rule
  forbidding `myapp.utils` from importing anything else under
  `myapp`. Equivalent to a guardrail for a single leaf layer.
- **Duplicate names in `layers`** are rejected at call time with
  `ValueError`. A duplicate would silently shadow whichever position
  it occupied earlier in the prefix, producing a rule with the wrong
  allowlist — better to fail loudly.
- **A name in `layers` that does not resolve to a real subpackage of
  `base`** is *not* rejected at construction time. Evaluation raises
  `KeyError` from `evaluate_rules` on the missing scope with the
  existing `"Found no node for path X in project."` message. Users
  catch typos via that error.
- **Dotted layer names** (e.g. `layered('myapp', ['core.utils',
  'core.db'])`) are not explicitly supported but happen to work because
  `f'{base}.{layer}'` is just string concatenation. Left undocumented
  unless a real use case appears; the documented contract is "layers
  are direct subpackage names of `base`."

### Failure message format

No new format. Failures are produced by the underlying
`must_only_import` predicates and rendered via the existing
`_format_target` and message construction. Lines like
`[scope myapp.db] must only import {myapp.utils} among descendants of
myapp — found myapp.template.x in …` flow through unchanged.

## Required code changes

### `src/pytest_imports/query.py`

Add the `layered` function near the other public factories. ~10 lines
including the duplicate check; no other code in `query.py` changes.

```python
from collections import Counter
from collections.abc import Sequence

def layered(base: str, layers: Sequence[str]) -> dict[Scope, MustOnlyImport]:
    """Strict N-tier layering rooted at `base`.

    Layer L_i may import descendants of layers[0..i-1] (and nothing else
    inside `base`). External / stdlib imports are unconstrained.
    """
    duplicates = sorted(name for name, count in Counter(layers).items() if count > 1)
    if duplicates:
        raise ValueError(f'duplicate layer name(s): {", ".join(duplicates)}')
    return {
        scope(f'{base}.{layer}'): must_only_import(
            [f'{base}.{lower}' for lower in layers[:i]],
            among=descendants(base),
        )
        for i, layer in enumerate(layers)
    }
```

### `src/pytest_imports/__init__.py`

Export `layered` and add to `__all__`.

### No changes needed in

- `model.py`, `parser.py`, `plugin.py`. `layered` returns a rule dict;
  everything downstream stays predicate-agnostic. `MustOnlyImport`
  already lives in the `Predicate` union (Part 1 prerequisite).

## Tests

### `test/unit/test_query.py`

- `layered('myapp', [])` returns `{}`.
- `layered('myapp', ['utils'])` returns a one-entry dict whose value
  is `must_only_import([], among=descendants('myapp'))`.
- `layered('myapp', ['utils', 'db'])`:
  - dict has exactly two entries.
  - `scope('myapp.utils')` value equals
    `must_only_import([], among=descendants('myapp'))`.
  - `scope('myapp.db')` value equals
    `must_only_import(['myapp.utils'], among=descendants('myapp'))`.
- `layered('myapp', ['a', 'b', 'a'])` raises `ValueError` whose message
  names the duplicate.
- The returned dict composes with another scope key via `**` and the
  final dict has the expected `len()`; verify dict-merge override on
  key collision (caller-supplied rule wins).

### `test/integration/`

A small sample tree with three layers `utils`, `db`, `presentation`
used end-to-end via `imports.check`:

- `presentation → db → utils` imports pass.
- `utils → db` produces a single `must_only_import` violation with the
  unchanged message format.
- `db → presentation` produces a violation against the `scope('…db')`
  rule.
- Imports of stdlib and a fake third-party name from `utils` are not
  flagged.

### `test/arch/`

Optional: apply `layered('pytest_imports', […])` to this project itself
if the actual import direction supports a strict ordering between
`model`, `parser`, `query`, `plugin`. Check first against the real
imports — adding a self-referential test that doesn't reflect reality
would be worse than nothing.

## Docs

### `README.md`

- Add `layered(base, layers)` to the quick-reference table:
  `` | `layered(base, layers)` | rule-dict helper | Builds a strict
  N-tier layering under `base` as a rule dict, ready for
  `imports.check`. | ``
- Add a short example section near the `must_only_import` example,
  showing the helper alongside its desugaring so readers see what it
  produces. Mention dict-merge composition with `**` for per-layer
  overrides.

### `AGENTS.md`

- One-line entry under **Data flow** noting that `layered` is a pure
  rule-dict builder over `must_only_import`, not a new predicate.

### `GLOSSARY.md`

No new terms. *Layer* and *layered* are used descriptively, not as
project-specific domain terms. Revisit only if future helpers
introduce a distinct vocabulary (e.g. *tier*, *band*).

## Open questions / non-goals

- **Modes** (strict vs. relaxed vs. skip-level-forbidden). Out of
  scope. One canonical convention; variants are expressible with raw
  `must_only_import`. A `mode=` parameter immediately invites a small
  DSL and a growing design surface.
- **Sibling-layer access** (two layers at the same level that may
  freely import each other). Out of scope. Users write
  `must_only_import` directly. A *level* concept inside the helper
  would multiply the API surface.
- **Auto-detection of layers** from subpackage names (alphabetical, by
  `__init__.py` metadata, by file count). Rejected. Layering is an
  editorial decision; deriving it from a directory listing makes the
  rule depend on accidental naming.
- **Per-layer `via=`** or **per-layer extra allowlist entries**. Out of
  scope. If one layer needs special treatment, dict-merge a manual
  `must_only_import` over the helper's output — the literal entry
  wins on key collision.
- **Validating that named layers exist** in the project at
  construction time. Out of scope. Evaluation already raises a clear
  `KeyError` from `evaluate_rules`; validating eagerly would require
  the helper to take the model, which it currently does not.
- **A separate `Layered` predicate / dataclass / evaluator arm.**
  Rejected. The whole point is that `layered` is a builder over
  existing primitives; promoting it to a predicate adds evaluator
  surface for no semantic gain. If a future requirement (e.g.
  cross-layer reporting summaries) genuinely needs predicate-level
  knowledge that "these rules form one layering," revisit.
- **Non-strict orderings** (e.g. a poset rather than a chain — "A and
  B both below C, but A and B unrelated"). Out of scope here; this is
  the territory where a more general dependency-graph DSL might one
  day live. Strict chain is the 95% case and the only one this helper
  handles.
- **Layers that span multiple base packages** (e.g. an `infra` layer
  drawn from both `myapp.infra` and `shared.infra`). Out of scope.
  The helper assumes one `base`; cross-package layerings are written
  manually.
