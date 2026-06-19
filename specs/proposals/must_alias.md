# Spec: `must_alias` predicate

## Motivation

Some libraries have a strongly conventional import alias (`numpy as np`,
`pandas as pd`, `tensorflow as tf`). This predicate lets a project enforce
that convention: whenever the target package would otherwise enter the
local namespace under any other name, the import is flagged.

Unlike `must_import`, this predicate does **not** require the module to
be imported. It only constrains *how* it is imported when it appears.

The rule is namespace-oriented, not statement-oriented: from-imports of
submodules and symbols (`from numpy import array`, `from scipy import
stats`) are allowed, because they don't bind `numpy`/`scipy` in the
local namespace — they only bind the imported member. This matches the
patterns that numpy, scipy, and pandas themselves recommend.

## Public API

```python
from pytest_imports import must_alias

def test_numpy_alias(imports):
    imports.check({
        project(): must_alias("numpy", "np"),
    })
```

Signature:

```python
def must_alias(path: str, alias: str) -> MustAlias: ...
```

Predicate dataclass: `MustAlias(path: str, alias: str)`, frozen, added to
the `Predicate` union in `query.py`.

## Semantics

A violation occurs when an import would either bind the target package
under the wrong name, or bind the canonical alias to something that
isn't the target package.

Concretely, for a rule `must_alias("numpy", "np")`:

| Import statement                  | Result    | Bound name(s)        |
| --------------------------------- | --------- | -------------------- |
| `import numpy as np`              | OK        | `np` → numpy         |
| `import numpy`                    | violation | `numpy` (wrong name) |
| `import numpy as foo`             | violation | `foo` (wrong alias)  |
| `import numpy.linalg`             | violation | `numpy` (Python binds top package) |
| `import numpy.linalg as nl`       | OK        | `nl` → numpy.linalg  |
| `import numpy.linalg as np`       | violation | `np` aliases wrong target |
| `from numpy import array`         | OK        | `array`              |
| `from numpy import linalg`        | OK        | `linalg`             |
| `from numpy.linalg import inv`    | OK        | `inv`                |
| `from numpy import *`             | violation | unspecified — namespace pollution |

The rule in three clauses, applied to any import whose `dot_path` is
relative to the target path:

1. **Star from-import** (`from numpy[.sub] import *`) — violation.
2. **Plain `import` statement** (`is_from_import is False`):
   - `asname is None` — violation (binds the bare top-level package name).
   - `dot_path == DotPath(target)` and `asname != alias` — violation
     (wrong alias for the target).
   - `dot_path != DotPath(target)` and `asname == alias` — violation
     (canonical alias points to a submodule instead of the target).
   - Otherwise — OK.
3. **Non-star from-import** (`is_from_import is True`, `alias.name != '*'`)
   — OK. The statement binds only the imported member, not the target.

Chained imports (`import numpy, scipy as sp`) are evaluated per alias —
each `ast.alias` entry is treated as its own import record.

Failure message format (mirrors other predicates):

```
[scope <label>] must import <path> only as <alias> — found in <file>:<line>
```

## Required code changes

### `src/pytest_imports/model.py`

Extend `ImportInModule`:

```python
@dataclass
class ImportInModule:
    dot_path: DotPath
    line_no: int
    level: int = 0
    asname: str | None = None       # NEW
    is_from_import: bool = False    # NEW
```

`is_from_import` is needed because `import a.b` and `from a import b`
currently both produce `dot_path=a.b, level=0` and are
indistinguishable.

### `src/pytest_imports/parser.py`

In `_collect_imports`:

- `ast.Import` branch: set `asname=alias.asname`, `is_from_import=False`.
- `ast.ImportFrom` branch: set `is_from_import=True`, and capture
  `asname=alias.asname` for completeness (`MustAlias` does not use it for
  from-imports, but future predicates may).

### `src/pytest_imports/query.py`

Add `MustAlias` dataclass, factory `must_alias`, include in `Predicate`
union, add a case arm in `_evaluate_predicate`.

Detection logic — for each import where
`import_by.dot_path.is_relative_to(DotPath(path))` is true, flag it
if **any** of the following hold:

- `is_from_import is True` and the last part of `dot_path` is `'*'`
  (star from-import).
- `is_from_import is False` and `asname is None` (plain `import` binds
  the bare top-level package name).
- `is_from_import is False` and `dot_path == DotPath(path)` and
  `asname != alias` (the target imported under the wrong alias).
- `is_from_import is False` and `dot_path != DotPath(path)` and
  `asname == alias` (the canonical alias bound to a submodule, not the
  target).

Otherwise, the import is OK. Note that non-star from-imports are always
OK under this predicate — they bind only the imported member.

### `src/pytest_imports/__init__.py`

Export `must_alias` and add to `__all__`.

## Tests

- `test/unit/test_parser.py` — assert `asname` and `is_from_import` are
  captured for each AST shape (`import x`, `import x as y`, `import x.y`,
  `from x import y`, `from x import y as z`, `from . import y`,
  `from x import *`, `import x, y as z`).
- `test/unit/test_query.py` — one test per row of the semantics table
  above, plus:
  - Path does not match, alias does: `import scipy as np` is not flagged
    by `must_alias("numpy", "np")`.
  - Submodule from-import with arbitrary asname is OK:
    `from numpy.linalg import inv as solve`.
  - Mixed file: a compliant `import numpy as np` and a violating
    `import numpy` in the same module produce exactly one failure for
    the violating line.
  - Scoping: rule only applied inside one package; violations elsewhere
    in the project are ignored.
- `test/integration/` — small sample tree end-to-end.

## Docs

- `README.md` — add to the API reference alongside `must_import`,
  `must_not_import`, etc.
- `AGENTS.md` — add `MustAlias` to the architecture section's predicate
  list under `query.py`.

## Open questions / non-goals

- **Multi-alias support** (e.g. permit `np` *or* `numpy`) is out of scope.
  Users who need it can wait or model it manually.
- **Strict mode** (also forbid from-imports like `from numpy import array`)
  is out of scope. If a user later wants it, add a `strict=True` flag —
  but only if there is concrete demand.
- **Internal modules with the same name** — the predicate keys off the
  dotted path regardless of origin (stdlib, third-party, internal). If a
  project has an internal module also named `numpy`, a plain
  `from . import numpy` that resolves to that internal module will not
  trigger the rule (it's a from-import), but `import numpy` shadowing
  attempts inside the project would. Scope the rule appropriately (e.g.
  exclude the conflicting subpackage via `scope(..., without=...)`) if
  this becomes a problem.
- The predicate makes no claim about whether the alias is *used* in the
  module body; it only checks the import statement form.
