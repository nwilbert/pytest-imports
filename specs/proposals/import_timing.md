# Spec: import timing (`timing=`)

## Motivation

Today the model treats every import the same, regardless of where the
statement sits or how it is written. Projects routinely care about
*when* an import executes:

- **top-level imports**: at module level, executed when the module is
  loaded.
- **lazy imports** (Python 3.15+, [PEP 810](https://peps.python.org/pep-0810/)):
  at module level, but executed on first use of the bound name. Written
  as `lazy import pandas` / `lazy from pandas import DataFrame`, or as a
  plain import of a module listed in `__lazy_modules__`.
- **function-level imports**: inside a function body, executed when the
  function runs. The traditional way to defer a dependency, break a
  cycle or shorten startup.
- **type-checking imports**: inside `if TYPE_CHECKING:`, never executed
  at runtime.

Concrete rules that users want to express:

- "No function-level imports of internal modules": cycles must be fixed
  by restructuring or with `TYPE_CHECKING`, not hidden in function
  bodies.
- "Loading the CLI must not load `pandas` or `tensorflow`": a lazy or
  function-level import is fine, a top-level one is not.
- "Required bootstrap imports must run at module top, not be hidden in
  a function or deferred."
- "`_typeshed` may only be imported under `TYPE_CHECKING`": it does not
  exist at runtime.
- "Defer with `lazy import`, not inside functions": once a project
  requires Python 3.15, ban function-level imports of third-party
  packages.

## Resolved design questions

### One flat partition of four timings

Every import gets exactly one **timing**: `'top'`, `'lazy'`,
`'function'` or `'type_checking'`. There are no union aliases and no
separate flags.

Keeping the three placements of an earlier draft and adding a separate
`lazy=True/False` flag was considered and rejected. Predicate filters
combine conjunctively, so the most common deferred-import rule, "lazy
*or* function-level", could not be written as a placement plus
`lazy=True`. With one flat set it is `timing=['lazy', 'function']`. The combinations an independent flag would
add are mostly impossible anyway: Python rejects `lazy` inside function
bodies, and a lazy import under `TYPE_CHECKING` never runs, so its
timing is `'type_checking'`.

The deciding factor for keeping the values disjoint is the **default
reading** of each:

- `must_import('foo', timing='top')` means "loading this module loads
  `foo`". If `'top'` included TYPE_CHECKING or lazy imports, the
  predicate would be satisfied by an import that never runs, or runs
  only later.
- `must_not_import('pandas', timing='top')` means "loading this module does
  not load `pandas`". If `'top'` included TYPE_CHECKING, the rule would
  also forbid annotating a parameter as `pandas.DataFrame` behind a
  TYPE_CHECKING block, which is usually fine and often desirable. If it
  included lazy imports, the rule would flag exactly the code that
  complies.

Users who want "anywhere but a function body" write
`timing=['top', 'lazy', 'type_checking']`. That is explicit, and the common
single-timing cases stay short.

### "Timing", not "placement"

An earlier draft of this spec called the concept *placement*, with three
values describing where the statement sits. A lazy import sits at module
level just like a top-level one; what differs is when it runs. All four
values answer the same question, so the concept is named **timing**.
The three existing literals keep their names.

### `timing=`, not `at=`

The earlier draft named the parameter `at=`, a preposition like `via=`,
`among=` and `without=`. With timing semantics it no longer fits:

- **It reads badly with the new value.** `at='top'` reads as "at top
  level", but `at='lazy'` reads as "at lazy", and `at='type_checking'`
  is borderline.
- **It does not say what it filters.** A newcomer could read it as a
  location such as a module (`at='myapp.cli'`). The `ValueError` would
  catch that, but the name invites the mistake.
- **It is easy to mix up with `among=`.** Both are short prepositions
  that narrow which imports count, but `among` takes a target and `at`
  a timing: `must_only_import('click', among=third_party(), at='top')`.
- **It breaks the ubiquitous language.** The glossary term, the model
  field (`ImportInModule.timing`), the `Timing` type and the error text
  all say "timing"; the parameter would be the only exception.

`timing=` reads well with every value (`timing='lazy'`,
`timing=['lazy', 'function']`) and uses the glossary term directly. It
gives up the preposition pattern, which matters less here: `via`,
`among` and `without` describe import style and scope, while this
option selects a property of the import itself. The failure messages
keep their own English phrases ("at top level", "as a lazy import").

Rejected alternatives:

- **`when=`** reads well for `'lazy'` but oddly for `'top'` and
  `'function'`, and it suggests a runtime condition, which is what the
  next section keeps it for.
- **`where=`** and **`placement=`** describe location, which is the
  framing this spec moved away from.
- **Longer names** such as `import_timing=` repeat the "import" already
  in `must_import(...)`.

PEP 810 calls every import that is not lazy *eager*, including
function-level ones. This project uses "eager" only in that PEP sense;
the `'top'` timing is called **top-level import** in the glossary, not
"eager import".

### `__lazy_modules__` is recognized

Code that must also run on Python before 3.15 cannot use the `lazy`
keyword; it is a SyntaxError there. Such code sets `__lazy_modules__`
instead, which 3.15 honors and older versions ignore. If the parser did
not recognize it, those imports would read as `'top'`, and a "loading
the CLI must not load `pandas`" rule would flag exactly the code that
complies.

The classification **does not depend on the interpreter running
pytest**: an import covered by `__lazy_modules__` is `'lazy'` even when
the tests run on 3.11, where it executes eagerly. A rule checks the
declared intent of the source. Tying the result to the interpreter would
make one rule pass on 3.15 and fail on 3.11 for the same code. Compare
`stdlib()`, which does follow the interpreter: there the interpreter
decides what a name refers to, while here it only decides whether a
declaration is honored.

### No other timings for top-level constructs

TYPE_CHECKING and lazy imports earn their slots because each changes
when the import executes, and each is signaled by a narrow,
easy-to-match syntax. Every other top-level construct (`try`/`except`,
`if sys.version_info ...`, `if sys.platform ...`,
`if __name__ == '__main__'`, `with`, `match`, class bodies) executes at
module load time on at least one code path, and the conditions are
arbitrary expressions with no clean partition. Adding
`top_conditional`, `top_version_gated` and the like is a slippery slope
with diminishing returns; most of those distinctions are better made on
the **target** axis (forbid importing `winreg` by name, forbid a
specific optional dependency).

If real demand emerges for a "wrapped in any conditional" signal, the
cleanest extension is an **orthogonal** option (e.g. `when=`), not more
timing literals.

### No `external()` target

An earlier draft of this spec also proposed `external()`. The
[stdlib/third-party spec](../stdlib_third_party.md) has since declined
it: `[stdlib(), third_party()]` covers it wherever targets combine
disjunctively. This spec's examples use `third_party()` instead.

## Public API

### `timing=` on predicates

```python
from pytest_imports import (
    internal, must_import, must_not_import, must_only_import, project, scope,
    third_party,
)

def test_no_function_level_internal_imports(imports):
    imports.check({
        project(): must_not_import(internal(), timing='function'),
    })

def test_cli_defers_heavy_deps(imports):
    # Loading the CLI must not load these; lazy and function-level
    # imports are both fine.
    imports.check({
        scope('myapp.cli'): must_not_import(['pandas', 'tensorflow'], timing='top'),
    })

def test_cli_loads_only_click_upfront(imports):
    # Every other third-party dependency of the CLI must be deferred.
    imports.check({
        scope('myapp.cli'): must_only_import('click', among=third_party(), timing='top'),
    })

def test_deferred_imports_use_pep_810(imports):
    # Requires 3.15: defer with `lazy import`, not inside functions.
    imports.check({
        project(): must_not_import(third_party(), timing='function'),
    })

def test_bootstrap_at_top(imports):
    imports.check({
        'myapp.bootstrap': must_import('myapp.config', timing='top'),
    })

def test_typeshed_only_for_type_checking(imports):
    # `_typeshed` does not exist at runtime.
    imports.check({
        project(): must_not_import('_typeshed', timing=['top', 'lazy', 'function']),
    })
```

Updated signatures:

```python
Timing = Literal['top', 'lazy', 'function', 'type_checking']

def must_import(
    path: Target | list[Target],
    *,
    via: Via | None = None,
    timing: Timing | list[Timing] | None = None,
) -> MustImport: ...

def must_not_import(
    path: Target | list[Target],
    *,
    via: Via | None = None,
    timing: Timing | list[Timing] | None = None,
) -> MustNotImport: ...

def must_not_import_private(
    path: Target | list[Target] | None = None,
    *,
    timing: Timing | list[Timing] | None = None,
) -> MustNotImportPrivate: ...

def must_only_import(
    allowed: Target | list[Target],
    *,
    among: Target = INTERNAL,
    via: Via | None = None,
    timing: Timing | list[Timing] | None = None,
) -> MustOnlyImport: ...
```

`timing=None` (the default) matches every timing, so existing rules keep
their meaning. `must_alias` does not take `timing=` (see non-goals).

## Semantics

### Timing classification

For each import, the parser assigns exactly one timing:

| Timing            | The statement is …                                                                               | Executes                       |
| ----------------- | ------------------------------------------------------------------------------------------------ | ------------------------------ |
| `'function'`      | inside a `def` or `async def` body, at any depth                                                 | when the function runs         |
| `'type_checking'` | inside the `body` of a recognized `if TYPE_CHECKING:` block, not inside a function               | never at runtime               |
| `'lazy'`          | in neither of the above, and marked `lazy` or covered by `__lazy_modules__` (see below)          | on first use of the bound name |
| `'top'`           | everything else: module level, class body, `try`/`except`, plain `if`, `with`, `match`, etc.     | when the module is loaded      |

When several would apply, the earlier row wins:

1. **Function wins.** An import inside a function inside an
   `if TYPE_CHECKING:` block is `'function'`. Once the parser descends
   into a `FunctionDef` / `AsyncFunctionDef`, every import below is
   `'function'`.
2. **TYPE_CHECKING beats lazy.** `if TYPE_CHECKING: lazy import foo` is
   legal (Python allows `lazy` inside `if`) but never runs, so it is
   `'type_checking'`.
3. **`else:` is not TYPE_CHECKING.** Only the `body` of a recognized
   `if TYPE_CHECKING:` block is `'type_checking'`; imports in its
   `orelse` keep the surrounding timing.
4. **Nested TYPE_CHECKING blocks stay TYPE_CHECKING.** The switch is
   one-way.

### `TYPE_CHECKING` recognition

The parser recognizes `if TYPE_CHECKING:` blocks by the shape of the
condition, regardless of how `TYPE_CHECKING` was imported:

| Source pattern                                            | AST `test`                                                         | Recognized                    |
| --------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------- |
| `from typing import TYPE_CHECKING`<br>`if TYPE_CHECKING:` | `ast.Name(id='TYPE_CHECKING')`                                     | yes                           |
| `import typing`<br>`if typing.TYPE_CHECKING:`             | `ast.Attribute(value=ast.Name(id='typing'), attr='TYPE_CHECKING')` | yes                           |
| `import typing as t`<br>`if t.TYPE_CHECKING:`             | `ast.Attribute(attr='TYPE_CHECKING')`, any prefix                  | yes                           |
| `from typing import TYPE_CHECKING as TC`<br>`if TC:`      | `ast.Name(id='TC')`                                                | **no** (limitation)           |
| `if not TYPE_CHECKING:`                                   | `ast.UnaryOp(...)`                                                 | **no**: body runs at runtime  |
| `if TYPE_CHECKING and sys.version_info > ...:`            | `ast.BoolOp(...)`                                                  | **no**: too risky to guess    |

Anything unrecognized falls back to the surrounding timing. False
negatives are acceptable: the import is treated as a runtime import,
which errs toward reporting under "must not import" rules. False
positives would silently hide runtime imports and are avoided.

### Lazy import recognition

**The `lazy` keyword.** Python 3.15 adds an `is_lazy` field to
`ast.Import` and `ast.ImportFrom`. The parser reads it with
`getattr(node, 'is_lazy', 0)`: the attribute does not exist on older
interpreters, and mypy checks against Python 3.11
(`[tool.mypy] python_version`), where typeshed does not declare it.

Python rejects `lazy` inside function bodies, class bodies and `try`
statements, and rejects `lazy from x import *`, but only when
*compiling*; `ast.parse` accepts all of them. The parser does not
re-validate: such an import is `'function'` inside a function and
`'lazy'` anywhere else. The module cannot be imported at all, so the
project's other tests fail regardless of how this plugin classifies it.

**`__lazy_modules__`.** A module-level `__lazy_modules__` makes some
plain imports in that module lazy. The behavior below was verified on
CPython 3.15.0rc2 and is what the parser reproduces:

| Statement (module named in `__lazy_modules__`)                | Lazy on 3.15                       |
| ------------------------------------------------------------- | ---------------------------------- |
| `import a`, `import a as b` (`'a'` listed)                    | yes                                |
| `from a import x`, `from a import x as y` (`'a'` listed)      | yes                                |
| `from pkg import sub`, `sub` a submodule (`'pkg'` listed)     | yes                                |
| `import pkg.sub` (only `'pkg'` listed)                        | **no**: needs `'pkg.sub'`          |
| `from .x import v` in package `rp` (`'rp.x'` listed)          | yes, matched on the resolved name  |
| `from a import *`                                             | **no**                             |
| inside a module-level `if`, `with`, `match`, `for`, `while`   | yes                                |
| inside a `try` body or an `except` / `except*` handler        | **no**                             |
| inside a `try` statement's `else:` or `finally:`              | yes                                |
| inside a class body                                           | **no**                             |
| before the `__lazy_modules__` assignment                      | **no**                             |

So a non-function, non-TYPE_CHECKING import is `'lazy'` via
`__lazy_modules__` iff all of the following hold:

- It is not inside a class body, a `try` body or an `except` /
  `except*` handler.
- It is not a star import.
- Its **statement module** is in the set in effect at that point. The
  statement module is the full dotted name for `import a.b` and the
  resolved absolute `from` module for `from ... import ...`, including
  relative ones.

The parser recognizes only assignments in the module body itself
(direct children of `ast.Module`), as `ast.Assign` or `ast.AnnAssign`
with a value, whose value is a list, tuple or set literal of string
constants. Such an assignment replaces the set for all statements after
it; CPython does the same. Any other top-level assignment to
`__lazy_modules__` (a non-literal value such as a string or a
`frozenset(...)` call, or `+=`) logs a warning and leaves the set
unchanged.

Known blind spots: CPython honors `+=`, in-place mutation
(`.append(...)`) and assignments nested in `if`/`try`, because it looks
`__lazy_modules__` up at the time each import runs. The parser does not
follow any of these. Imports they would make lazy classify as `'top'`,
which errs toward reporting.

Process-wide switches are runtime configuration and invisible to a
static parser: `-X lazy_imports=all` and `sys.set_lazy_imports('all')`
make every eligible import lazy (the other accepted mode is
`'normal'`), and a `sys.set_lazy_imports_filter()` callback can force
individual lazy imports to run eagerly. See non-goals.

### Class bodies, conditionals, `try`/`except`

All of these execute at module-load time and are `'top'`:

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

With `__lazy_modules__ = ['tomllib', 'tomli']` above them, the two
imports under `if`/`else` would be `'lazy'`; the `try`/`except` and
class-body imports stay `'top'`, matching CPython.

The plugin does **not** model "conditionally executed at runtime"
beyond these special cases. Optional-dependency patterns
(`try: import optional / except ImportError: optional = None`) read as
top-level imports, which matches how users reason about them: the
project *can* load `optional`, just maybe not on every machine.

### Interpreter dependence

- **`lazy` syntax** needs Python 3.15 to parse. On 3.11–3.14,
  `ast.parse` raises SyntaxError and the parser skips the file, so
  *all* of that file's imports disappear from the model and rules over
  it pass. Today the skip is only logged, and pytest shows captured
  logs only for failing tests, so in this case nobody would see it.
  When parsing fails, the interpreter is older than 3.15, and the
  source contains a line matching `^\s*lazy\s+(import|from)\s`, the
  parser therefore also calls `warnings.warn(...)` (a `UserWarning`)
  saying the file uses PEP 810 lazy imports and pytest must run on
  Python 3.15+ to check it. pytest lists it in the warnings summary of
  every run, and projects with `filterwarnings = error` get a failure.
- **`__lazy_modules__`** classification is interpreter-independent; see
  the resolved design question above.

### Matching `timing=` values

A predicate with a `timing` filter considers an import iff the import's
timing is in the normalized set:

| `timing=` value                      | Matches timings                        | Reads as                     |
| ------------------------------------ | -------------------------------------- | ---------------------------- |
| `None`                               | all four                               | (no filter)                  |
| `'top'`                              | `{top}`                                | loaded with the module       |
| `'lazy'`                             | `{lazy}`                               | declared lazy                |
| `'function'`                         | `{function}`                           | inside a function            |
| `'type_checking'`                    | `{type_checking}`                      | annotations only             |
| `['lazy', 'function']`               | `{lazy, function}`                     | deferred                     |
| `['top', 'lazy', 'function']`        | everything but `type_checking`         | runs at runtime              |
| `['top', 'lazy', 'type_checking']`   | everything but `function`              | not inside a function        |

The factory normalizes `timing` to a `frozenset[Timing]`. An empty
list, or any value that is not one of the four literals, raises
`ValueError` when the rule is built: `Literal` is not enforced at
runtime, and a typo like `timing='toplevel'` would otherwise match
nothing and make every `must_not_import` rule pass.

### Per-predicate behavior

- **`MustImport`**: for each target, satisfied iff some import in scope
  matches the target, `via` and `timing`. Still one failure per
  unsatisfied target, at scope level.
- **`MustNotImport`**: imports with a timing outside the `timing` filter
  are ignored. Each remaining import matching any target is one
  failure, as today.
- **`MustNotImportPrivate`**: imports with a timing outside the `timing`
  filter are ignored.
- **`MustOnlyImport`**: `timing` narrows the checked universe the same
  way `among` and `via` do: only imports matching `among`, `via` and
  `timing` are checked against `allowed`.

### Failure messages

When `timing` is set, the rule part of each message gets a timing
phrase; it is omitted when `timing` is `None`. Each label carries its
own preposition, so every combination reads as English:

| Timing            | Rule phrase                | Short label           |
| ----------------- | -------------------------- | --------------------- |
| `'top'`           | `at top level`             | `top level`           |
| `'lazy'`          | `as a lazy import`         | `lazy`                |
| `'function'`      | `at function level`        | `function level`      |
| `'type_checking'` | `in a TYPE_CHECKING block` | `TYPE_CHECKING block` |

Several timings are joined with `or`, in the order of the table above
(not alphabetically), e.g. `as a lazy import or at function level`.

The phrase goes at the end of the rule part, right before ` — `:

| Predicate              | Rule part                                                          |
| ---------------------- | ------------------------------------------------------------------ |
| `MustImport`           | `must import <targets> <phrase>`                                   |
| `MustNotImport`        | `must not import <targets> <phrase>`                               |
| `MustNotImportPrivate` | `must not import private names[ from <targets>] <phrase>`          |
| `MustOnlyImport`       | `must only import <allowed> among <among> <phrase>`                |

When the `timing` filter names more than one timing, each reported
import also carries its actual timing as ` (<short label>)` at the very
end of the message, after the location. Putting it last works the same
for every predicate, including `MustNotImportPrivate`, whose message
names no dotted path, and it does not interact with `MustNotImport`'s
`matching <target>` segment:

```
  [scope myapp.bootstrap] must import myapp.config at top level — no matching import found
  [scope myapp.cli] must not import {pandas, tensorflow} at top level — found pandas matching pandas in src/myapp/cli/main.py:3
  [scope myapp.cli] must not import any third-party module as a lazy import or at function level — found requests in src/myapp/cli/main.py:42 (function level)
  [scope myapp] must not import private names from any internal module at top level or at function level — found in src/myapp/core.py:7 (top level)
```

## Required code changes

### `src/pytest_imports/model.py`

- Add `Timing = Literal['top', 'lazy', 'function', 'type_checking']`.
  It lives in `model` because both `parser` and `query` need it, and
  the arch tests allow `parser` to import only `model`.
- Add a `timing: Timing = 'top'` field to `ImportInModule` and describe
  it in the docstring.

### `src/pytest_imports/parser.py`

Replace the `ast.walk` loop in `_collect_imports` with a recursive
descent that carries a context down the tree. `_collect_imports`
keeps taking an `ast.Module`, so tests can hand it a tree built in
memory (see [Tests](#tests)). Keep the relative-import resolution
unchanged, and extract the per-statement conversion so both statement
kinds share the timing decision.

Sketch:

```python
@dataclass(frozen=True)
class _Context:
    # 'top', 'function' or 'type_checking'; 'lazy' is decided per statement.
    timing: Timing = 'top'
    # False where CPython ignores `__lazy_modules__`: class bodies, `try`
    # bodies and `except` handlers.
    lazy_eligible: bool = True


class _ImportCollector:
    def __init__(self, package_path: DotPath, module_path: Path) -> None:
        self.imports: list[ImportInModule] = []
        self._lazy_modules: frozenset[str] = frozenset()
        ...

    def collect(self, module_ast: ast.Module) -> list[ImportInModule]:
        for stmt in module_ast.body:
            self._update_lazy_modules(stmt)  # recognizes top-level assignments only
            self._visit(stmt, _Context())
        return self.imports

    def _visit(self, node: ast.AST, ctx: _Context) -> None:
        match node:
            case ast.Import() | ast.ImportFrom():
                self._add(node, ctx)
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                self._visit_children(node, replace(ctx, timing='function'))
            case ast.ClassDef():
                self._visit_children(node, replace(ctx, lazy_eligible=False))
            case ast.Try() | ast.TryStar():
                ineligible = replace(ctx, lazy_eligible=False)
                self._visit_all(node.body, ineligible)
                self._visit_all(node.handlers, ineligible)
                self._visit_all(node.orelse, ctx)
                self._visit_all(node.finalbody, ctx)
            case ast.If() if ctx.timing != 'function' and _is_type_checking(node.test):
                self._visit_all(node.body, replace(ctx, timing='type_checking'))
                self._visit_all(node.orelse, ctx)
            case _:
                self._visit_children(node, ctx)

    def _visit_children(self, node: ast.AST, ctx: _Context) -> None:
        # Imports are statements, so expression subtrees are skipped.
        children = [
            child
            for child in ast.iter_child_nodes(node)
            if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case))
        ]
        self._visit_all(children, ctx)

    def _timing(self, node, statement_module: DotPath, ctx: _Context) -> Timing:
        if ctx.timing != 'top':
            return ctx.timing
        if getattr(node, 'is_lazy', 0) or (
            ctx.lazy_eligible
            and not _is_star(node)
            and str(statement_module) in self._lazy_modules
        ):
            return 'lazy'
        return 'top'


def _is_type_checking(test: ast.expr) -> bool:
    match test:
        case ast.Name(id='TYPE_CHECKING') | ast.Attribute(attr='TYPE_CHECKING'):
            return True
    return False
```

For `import a.b, c` the statement module is decided per alias; for
`from ... import ...` it is the resolved `from` path, which the parser
already computes.

**Import order changes.** `ast.walk` traverses breadth-first, so today a
module's imports are ordered by nesting depth first: a top-level import
on line 3 comes before a function-level import on line 2. The recursive
descent yields them in source order. Failure messages are emitted in
import order, so they will now follow line order, which is easier to
read. Check tests that compare lists of imports or failures for nested
imports.

**Performance.** Skipping expression subtrees means the new traversal
visits far fewer nodes than `ast.walk`, which visits every expression.
Run `uv run nox -s benchmark` before and after to confirm the model
build does not get slower.

**SyntaxError hint.** In the SyntaxError branch of
`build_import_model`, add the PEP 810 hint described under
[Interpreter dependence](#interpreter-dependence). Keep the version
check in a module-level flag so tests can monkeypatch it on any
interpreter. The `warnings.warn` call goes outside the
`warnings.catch_warnings()` block that silences parse-time warnings.

```python
_HAS_LAZY_SYNTAX = sys.version_info >= (3, 15)
_LAZY_IMPORT_LINE = re.compile(rb'^\s*lazy\s+(import|from)\s', re.MULTILINE)
```

### `src/pytest_imports/query.py`

- Add a `timing: frozenset[Timing] | None = None` field to `MustImport`,
  `MustNotImport`, `MustNotImportPrivate` and `MustOnlyImport`. The
  factories accept `Timing | list[Timing] | None` and normalize via a
  helper next to `_as_target_tuple`. `_TIMINGS` is the ordered tuple
  `typing.get_args(Timing)`, which also gives the order for joined
  labels:

  ```python
  def _as_timing_set(timing: Timing | list[Timing] | None) -> frozenset[Timing] | None:
      if timing is None:
          return None
      timings = frozenset([timing] if isinstance(timing, str) else timing)
      if not timings or not timings.issubset(_TIMINGS):
          raise ValueError(...)
      return timings
  ```

- Thread the predicate's `timing` set through `_find_imports_matching_any`
  (and so `_find_matching_imports`) next to `via`, and through
  `_find_matching_private_imports`. Inside these helpers, name the
  parameter `timings`, so it does not read like `import_by.timing`:

  ```python
  if timings is not None and import_by.timing not in timings:
      continue
  ```

- In `_evaluate_predicate`, add the timing phrase and, when `timing`
  names more than one timing, the trailing short label per
  [Failure messages](#failure-messages):
  one dict of `(phrase, short label)` per timing plus a
  `_format_timings(timings)` helper that joins phrases in `_TIMINGS` order.

### `src/pytest_imports/__init__.py`, `plugin.py`

No changes. `Timing` is not exported; it stays reachable as
`pytest_imports.model.Timing` for custom helpers.

## Tests

### Coverage and CI constraints

- The `coverage` session requires 100% line coverage. It runs on the
  newest stable Python uv selects, 3.14 today and 3.15 once 3.15.0 is
  released. Neither side of the 3.15 split may leave lines uncovered.
- `pytest_compat`, the only session that runs on Python 3.15 today, is
  triggered manually (`workflow_dispatch`), not on push or PR.

So every interpreter-specific path gets a test that runs on **every**
interpreter. Tests that need real 3.15 syntax are an extra end-to-end
check on top.

### `test/unit/test_parser.py` (new)

Tests that call `_collect_imports` on an `ast.Module` built in memory,
without the filesystem:

- `ast.parse('import a')` and `ast.parse('from a import b')`, with
  `is_lazy = 1` set on the statement node → `'lazy'`. Also inside a
  module-level `if`, and under `if TYPE_CHECKING:` → `'type_checking'`.
  This covers the `lazy` keyword path on every interpreter.

### `test/integration/test_parser.py`

On all interpreters:

- Module level, `try` body, `except` handler, class body, plain
  `if`/`with` → `'top'`.
- `if TYPE_CHECKING:` (`Name` and `Attribute` forms) → `'type_checking'`;
  its `else:` → surrounding timing; nested TYPE_CHECKING → still
  `'type_checking'`.
- `def`, `async def`, method, nested function → `'function'`;
  `if TYPE_CHECKING:` inside a `def` → `'function'`.
- Aliased `TYPE_CHECKING` and `if not TYPE_CHECKING:` → `'top'`.
- `__lazy_modules__`, one case per row of the table in
  [Lazy import recognition](#lazy-import-recognition): list, tuple and
  set literals; an annotated assignment; imports before the assignment;
  reassignment replaces the set; `try` body / `except` / `except*` vs.
  `else` / `finally`; class body; star import; `import pkg.sub` with
  only `'pkg'` listed; a relative `from .x import v`; a
  `__lazy_modules__` import under `if TYPE_CHECKING:` →
  `'type_checking'`; inside a function → `'function'`.
- A non-literal `__lazy_modules__` assignment logs a warning, and the
  set in effect stays as it was.
- Source order: a function-level import above a top-level import comes
  first in `imports`.
- The SyntaxError hint, with `_HAS_LAZY_SYNTAX` monkeypatched to
  `False`: a file with a `lazy import` line plus an unrelated syntax
  error (so it fails to parse on every interpreter) emits a
  `UserWarning` mentioning PEP 810 and Python 3.15
  (`pytest.warns`). With the flag `True`, the same file only logs.

Python 3.15+ only (`skipif(sys.version_info < (3, 15))`), as an
end-to-end check of the in-memory tests above:

- `lazy import a`, `lazy from a import b` → `'lazy'`, also inside a
  module-level `if` and `with`.
- `if TYPE_CHECKING: lazy import a` → `'type_checking'`.

### `test/unit/test_query.py`

For each of `must_import`, `must_not_import`, `must_not_import_private`
and `must_only_import`:

- `timing=None` matches every timing (existing tests stay green).
- Each single timing matches only itself.
- `['lazy', 'function']` and `['top', 'lazy', 'type_checking']` match
  their unions and nothing else.
- `must_only_import(..., timing='top')` ignores non-allowed imports with
  other timings.

Factories: `timing=[]` and `timing='toplevel'` raise `ValueError`.

### `test/unit/test_plugin.py`

Failure messages, for every predicate in the
[rule-part table](#failure-messages): a single timing (phrase, no
trailing label), several timings (phrases joined in table order,
trailing short label), and `timing=None` (unchanged messages). Include
`MustNotImport` with several targets, so both `matching <target>` and
the trailing label appear.

### `test/integration/`

A sample tree covering all four timings:

```
pkg/
  __init__.py      # import os                                  (top)
  bootstrap.py     # __lazy_modules__ = ['requests']
                   # import requests                            (lazy)
                   # import pandas                              (top)
                   # if TYPE_CHECKING: from .types import T     (type_checking)
                   # def go(): from .heavy import H             (function)
  types.py
  heavy.py
```

Rules:

- `project(): must_not_import(internal(), timing='function')`: one
  violation, `bootstrap.go` importing `.heavy`.
- `'pkg.bootstrap': must_import('pkg.types', timing='type_checking')`: OK.
- `'pkg.bootstrap': must_not_import(third_party(), timing='top')`: one
  violation, `pandas`.
- `'pkg.bootstrap': must_import('requests', timing='lazy')`: OK on every
  interpreter.

### `test/arch/test_imports.py`

Add `project(): must_not_import(internal(), timing='function')`. The plugin
has no function-level imports today; the rule keeps the layering checks
honest by forbidding cycles hidden in function bodies.

## Docs

### `README.md`

- **Building blocks**: add a `timing=` row next to `via=`.
- **Examples**: a new "Import timing" section after "Absolute vs.
  relative imports", showing `must_not_import(..., timing='top')` for a
  deferred heavy dependency and `must_not_import(internal(),
  timing='function')`.
- **Details**: a new "Import timing" subsection with the classification
  table, the priority rules, the `__lazy_modules__` rules and blind
  spots, the aliased `TYPE_CHECKING` limitation, and the warning that
  `lazy` syntax requires running pytest on Python 3.15+.

### `AGENTS.md`

- **Data flow**: mention `ImportInModule.timing` in the `model.py`
  bullet and the context-carrying recursive descent in the `parser.py`
  bullet. List `timing=` in the `query.py` bullet.
- **Key internals**: the priority order (function > type_checking >
  lazy > top); `TYPE_CHECKING` recognition is AST-shape based and
  narrow; `__lazy_modules__` is recognized only as a top-level literal
  assignment and does not depend on the interpreter; imports are
  collected in source order.

### `GLOSSARY.md`

Add under **Imports**:

- **timing**: when an import executes. One of `'top'`, `'lazy'`,
  `'function'`, `'type_checking'`; recorded as `ImportInModule.timing`
  and filtered with `timing=`.
- **top-level import**: an import executed while its module is loaded:
  at module level, in a class body, or in a `try`/`except`, `if`,
  `with` etc. at module level, and neither lazy nor inside a recognized
  `if TYPE_CHECKING:` block. The `'top'` timing. Lazy imports also sit
  at module level but are not top-level imports in this sense.
- **lazy import**: an import declared lazy per
  [PEP 810](https://peps.python.org/pep-0810/), either with the `lazy`
  keyword or through `__lazy_modules__`, and executed on first use of
  the bound name. The `'lazy'` timing. **Only** use "lazy import" in
  this sense, never for function-level imports.
- **eager import**: PEP 810's term for any import that is not lazy,
  including function-level ones. Do not use it as a name for the
  `'top'` timing.
- **function-level import**: an import inside a `def` or `async def`
  body, at any depth. The `'function'` timing. Function-level beats
  TYPE_CHECKING.
- **type-checking import**: an import inside the `body` of a recognized
  `if TYPE_CHECKING:` block, outside any function. Never executed at
  runtime. The `'type_checking'` timing.
- **deferred import**: a lazy or function-level import, i.e.
  `timing=['lazy', 'function']`.
- **statement module**: the module an import statement names: the full
  dotted name for `import a.b`, the resolved absolute `from` module for
  `from ... import ...`. Matched against `__lazy_modules__`. For
  from-imports it differs from `ImportInModule.dot_path`, which also
  includes the imported name.

## Non-goals and open questions

- **More conditional timings** beyond TYPE_CHECKING and lazy imports;
  see the resolved design question above.
- **Aliased `TYPE_CHECKING`** (`from typing import TYPE_CHECKING as TC`)
  requires tracking name bindings in the module. Documented limitation;
  revisit if it bites.
- **Following `__lazy_modules__` beyond top-level literal assignments**
  (`+=`, `.append(...)`, assignments nested in `if`/`try`). Revisit if
  real code uses these forms.
- **Process-wide lazy-import modes** (`-X lazy_imports=all`,
  `sys.set_lazy_imports()`, `sys.set_lazy_imports_filter()`). They are
  runtime configuration; `timing='lazy'` means "declared lazy in the
  source".
- **Making all skips visible.** Everything the parser skips (a file
  with a SyntaxError, a `.py` file shadowed by a package of the same
  name, a relative import beyond the top-level package) is only logged
  today, which pytest hides for passing tests. This spec adds a `UserWarning` only for the
  PEP 810 case. Whether to warn for, or fail on, every skipped file is
  a separate decision.
- **`timing=` on `must_alias`**: the alias rule is the same wherever the
  import runs. Add only if someone asks.
- **Nested-function granularity** (a function-level import in a
  module-level function vs. a closure inside a method). Both are
  `'function'`.
- **Ruff compilation**: if the [ruff_compile](ruff_compile.md) proposal
  is implemented, it should skip rules with `timing=` at first. Ruff's
  `banned-module-level-imports` (TID253) may be able to express part of
  `timing='top'`; that needs investigating.
- **Union aliases** such as `'deferred'` or `'runtime'` are not added;
  the lists in [Matching](#matching-timing-values) are short enough. See
  [`timing=`, not `at=`](#timing-not-at) for the parameter name.
