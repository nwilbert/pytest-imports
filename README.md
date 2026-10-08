# pytest-imports

*A pythonic derivative of [ArchUnit](https://www.archunit.org), in the form of a [pytest](https://www.pytest.org) plugin.*

pytest-imports lets you write tests for the architecture of your Python project by checking its import statements.

## Quick start

Install `pytest-imports` with the package manager of your choice (e.g. pip or uv). It works out of the box for `src/` and flat layouts (see [Configuration](#configuration)), so you can use the `imports` fixture right away:

```python
from pytest_imports import must_import, must_not_import, scope

def test_imports(imports):
    imports.check({
        scope('foo'): must_import('bar'),
        scope('baz'): must_not_import('qux'),
    })
```
This checks that module `foo` imports `bar`, and that module `baz` does not import `qux`.

Rules include descendants on both sides: an import of `bar.x` anywhere in `foo` or its descendants satisfies `scope('foo'): must_import('bar')`. Dot paths in rules are always fully qualified, even where the source uses relative imports. See [Terminology](#terminology) for what we mean by *descendant*, *submodule* and *subpackage*.

## Building blocks

| Name | Kind | Purpose |
|---|---|---|
| [`scope(path)`](#example-layered) | scope | Restrict a rule to `path` and its descendants. |
| [`scope(path, without=...)`](#example-layered) | scope | Same, but exclude named submodules or subpackages. |
| [`project()`](#example-private) | scope | All modules under the configured source roots. |
| [`must_import(targets)`](#example-layered) | predicate | Require an import of the target (or a descendant) in scope. With a list, every target is required. |
| [`must_not_import(targets)`](#example-layered) | predicate | Forbid imports of the target (or a descendant) in scope. With a list, any target is forbidden. |
| [`must_only_import(allowed, among=internal())`](#example-only) | predicate | Within `among`, allow only the listed targets. |
| [`must_not_import_private(targets)`](#example-private) | predicate | Forbid imports of private (`_`-prefixed) names; the optional targets narrow which ones are flagged. |
| [`must_alias(path, alias)`](#example-alias) | predicate | Require that `path` enters a namespace only under `alias` (e.g. `numpy as np`). |
| [`descendants(path, without=...)`](#example-descendants) | target | Match descendants of `path` but not `path` itself. |
| [`internal()`](#example-internal) | target | Match any import resolving inside the source roots. |
| [`stdlib()`](#example-stdlib) | target | Match any non-internal import of a standard library module. |
| [`third_party()`](#example-stdlib) | target | Match any import that is neither internal nor stdlib. |
| [`via='absolute'` / `via='relative'`](#example-via) | option | Restrict a predicate to one import style. |
| [`timing='top'` / `'lazy'` / `'function'` / `'type_checking'`](#example-timing) | option | Restrict a predicate to imports that execute at that time; a list matches any of them. |

A *target* is either a dotted-path string or one of the target helpers above.

## Examples

<a id="example-layered"></a>
### Layered architecture

```python
from pytest_imports import must_import, must_not_import, scope

def test_layered_architecture(imports):
    imports.check({
        scope('myapp', without='api'): must_not_import('myapp.api'),
        scope('myapp.api'): must_import('myapp.core'),
    })
```
`scope('myapp', without='api')` covers all of `myapp` except `myapp.api` and its descendants. The excluded name can be a subpackage (`api/`) or a module file (`plugin.py`). Pass a list to exclude several (`without=['api', 'adapters']`), or a dotted path to exclude a deeper subtree (`without='db.migrations'` leaves the rest of `myapp.db` in scope).

### Several rules per scope

```python
def test_multiple_rules_per_scope(imports):
    imports.check({
        scope('myapp', without=['adapters']): [
            must_not_import(['sqlalchemy', 'flask']),
            must_import('myapp.core'),
        ],
    })
```
- A list of *targets* in `must_not_import` is disjunctive: an import of either is a violation, and the failure message names which one matched.
- A list of targets in `must_import` is conjunctive: every target must be imported somewhere in scope.
- A list of *predicates* applies several rules to one scope. All failures are reported together.

<a id="example-via"></a>
### Absolute vs. relative imports

```python
def test_no_relative_imports_in_public_api(imports):
    imports.check({
        scope('myapp.api'): must_not_import('myapp', via='relative'),
    })
```
`via='absolute'` or `via='relative'` restricts a rule to that import style; without `via`, both match.

<a id="example-timing"></a>
### Import timing

```python
from pytest_imports import internal, must_not_import, project, scope

def test_cli_defers_heavy_dependencies(imports):
    imports.check({
        # Loading the CLI must not load these; lazy and function-level imports are fine.
        scope('myapp.cli'): must_not_import(['pandas', 'tensorflow'], timing='top'),
        # Cycles must be fixed, not hidden in function bodies.
        project(): must_not_import(internal(), timing='function'),
    })
```
`timing=` restricts a rule to imports that execute at a given time:

- `'top'`: while the module is loaded (module level, class bodies, `try`, `if`, …).
- `'lazy'`: on first use of the bound name, per [PEP 810](https://peps.python.org/pep-0810/) (`lazy import pandas`, or a module listed in `__lazy_modules__`).
- `'function'`: inside a function body, when the function runs.
- `'type_checking'`: inside `if TYPE_CHECKING:`, never at runtime.

A list matches any of them, e.g. `timing=['lazy', 'function']` for deferred imports. Without `timing`, every import matches. See [Import timing](#timing-details) for the exact rules.

<a id="example-descendants"></a>
### Encapsulating a package's internals

```python
from pytest_imports import descendants, must_not_import, scope

def test_capture_internals_are_encapsulated(imports):
    imports.check({
        scope('myapp', without='capture'):
            must_not_import(descendants('myapp.capture')),
    })
```
`descendants('myapp.capture')` matches `myapp.capture.parser`, `myapp.capture.config`, … but **not** `myapp.capture` itself. So the rest of `myapp` may use the public surface (`import myapp.capture`) but not the internals. The plain string `'myapp.capture'` would flag both.

`without=` carves subtrees out of the match, relative to the path: `descendants('myapp.contrib', without='admin')` matches everything under `myapp.contrib` except `myapp.contrib.admin` and its descendants. It takes the same shapes as `scope(without=...)`, and pairs well with [`must_only_import`](#example-only) to say "allow everything under X except Y".

<a id="example-internal"></a>
### Internal imports

```python
from pytest_imports import internal, must_not_import, project

def test_internal_imports_are_relative(imports):
    imports.check({
        project(): must_not_import(internal(), via='absolute'),
    })
```
`internal()` matches every import that resolves to a module under the configured source roots. With `via='absolute'`, this rule requires all internal imports to be relative: `from .aaa import ...` rather than `from myapp.core.aaa import ...`, including across packages (e.g. `myapp.other` imported from `myapp.core.bbb`).

This is the opposite of ruff's [TID252 (relative-imports)](https://docs.astral.sh/ruff/rules/relative-imports/#relative-imports-tid252), which bans relative imports in favor of absolute ones.

<a id="example-only"></a>
### Allowlists

```python
from pytest_imports import must_only_import, scope

def test_api_layer_imports(imports):
    imports.check({
        scope('myapp.api'): must_only_import(['myapp.core', 'myapp.schemas']),
    })
```
`must_only_import` is the allowlist counterpart of `must_not_import`: within a universe of imports, only the listed targets are allowed.

- The universe is `among`, which defaults to `internal()`. So the rule above says "`myapp.api` may only reach into `myapp.core` and `myapp.schemas`", and leaves stdlib and third-party imports alone.
- Change `among` to narrow or shift the universe, e.g. `among=descendants('myapp')` to police only `myapp.*`, or `among=third_party()` to allowlist external dependencies (see [below](#example-stdlib)).
- An empty allowlist, `must_only_import([])`, forbids every import within `among`: a guardrail for a leaf module that must not reach back into the project.

<a id="example-private"></a>
### Private imports

```python
from pytest_imports import must_not_import_private, project

def test_no_private_imports(imports):
    imports.check({
        project(): must_not_import_private(),
    })
```
`must_not_import_private()` flags any import with a dotted-path part starting with `_` (except `__future__`). [`project()`](#configuration) covers every module under the source roots. Optional targets narrow which private imports are flagged:

- `must_not_import_private('myapp')`: only those from `myapp`.
- `must_not_import_private(descendants('myapp.capture'))`: only those from that subtree.
- `must_not_import_private(internal())`: only those of project modules.
- `must_not_import_private([internal(), third_party()])`: all except the stdlib.

<a id="example-alias"></a>
### Import aliases

```python
from pytest_imports import must_alias, project

def test_numpy_alias(imports):
    imports.check({
        project(): must_alias('numpy', 'np'),
    })
```
`must_alias('numpy', 'np')` flags any import that brings `numpy` into a module's namespace under another name:

- Rejected: `import numpy` (bare name), `import numpy as foo` (wrong alias), `import numpy.linalg` (binds the bare `numpy`), `import numpy.linalg as np` (`np` bound to a submodule), and `from numpy import *`.
- Accepted: `import numpy as np`, `import numpy.linalg as nl`, and from-imports of members or submodules (`from numpy import array`), since they don't bind `numpy` itself.

Unlike `must_import`, it does **not** require `numpy` to be imported at all.

<a id="example-stdlib"></a>
### Stdlib and third-party dependencies

```python
from pytest_imports import (
    internal, must_not_import, must_not_import_private, must_only_import,
    project, scope, stdlib, third_party,
)

def test_external_dependencies(imports):
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
`stdlib()` and `third_party()` let you say "no third-party dependencies here" without listing every installed package, so the rule doesn't go stale when a dependency is added. How imports are classified, and the caveats, are described under [Internal, stdlib and third-party imports](#internal-stdlib-and-third-party-imports).

### Reporting violations without failing

For dashboards, ratchets or benchmarks, use `imports.violations(rules)` instead of `imports.check(rules)`. It takes the same rules and returns the violation messages instead of raising:

```python
def test_track_legacy_couplings(imports):
    failures = imports.violations({
        scope('myapp.api'): must_not_import('myapp.legacy'),
    })
    print(f'{len(failures)} legacy coupling(s) remain')
```

`check()` is `violations()` plus an `AssertionError` when the list is non-empty.

## Details

### Terminology

This project keeps a consistent vocabulary; see [GLOSSARY.md](GLOSSARY.md) for the full list. The key distinctions:

- **submodule** of `X`: a direct child of package `X`, either a `.py` file or a subpackage.
- **subpackage** of `X`: a submodule of `X` that is itself a package.
- **descendant** of `X`: a module nested under `X` at *any* depth. `a.b.c` is a descendant of `a`, but a submodule only of `a.b`.

### How it works

The plugin parses your source files with the standard library's `ast` module and collects their import statements the first time a test uses the `imports` fixture. The analysis is static and superficial:

- Python is dynamic, so the rules are easy to circumvent on purpose. The plugin assumes a "friendly" codebase.
- It does not track how imported names are used. After `import a`, a call to `a.b()` does not count as importing `a.b`.
- Only files under the [source roots](#configuration) are analyzed.
- Relative imports that Python itself rejects (one in a top-level module, or one that climbs beyond the top-level package) are skipped with a warning.

### Internal, stdlib and third-party imports

Every import falls into exactly one of three classes:

| Target | Matches |
| --- | --- |
| `internal()` | The import resolves to a module under the configured source roots. |
| `stdlib()` | Not internal, and the top-level name is in [`sys.stdlib_module_names`](https://docs.python.org/3/library/sys.html#sys.stdlib_module_names). |
| `third_party()` | Neither internal nor stdlib. |

- **Internal wins.** If your project has its own top-level `logging` package, imports of it match `internal()` only. Relative imports are always internal.
- **`__future__` is stdlib**, so a stdlib allowlist must name it to permit `from __future__ import annotations`.
- **Typeshed-only modules** such as `_typeshed` are not in `sys.stdlib_module_names`, so they count as third-party.
- **Stdlib membership depends on the Python version running pytest**, but not on the platform (`winreg` is stdlib everywhere). For example, `annotationlib` is third-party before 3.14, and `distutils` is third-party on 3.12+. For a version-dependent fallback such as `try: from compression import zstd` / `except ImportError: from backports import zstd`, use an allowlist rather than a ban, so the rule passes on every version: `must_only_import(['compression', 'backports.zstd'], among=third_party())`.

<a id="timing-details"></a>
### Import timing

Every import gets exactly one timing. When several rows apply, the first one wins:

| Timing | The import statement is … | Executes |
| --- | --- | --- |
| `'function'` | inside a `def` or `async def` body, at any depth | when the function runs |
| `'type_checking'` | inside the body of an `if TYPE_CHECKING:` block, not inside a function | never at runtime |
| `'lazy'` | marked `lazy`, or covered by `__lazy_modules__` (see below) | on first use of the bound name |
| `'top'` | anywhere else: module level, class body, `try`/`except`, `if`, `with`, `match`, … | when the module is loaded |

- **`TYPE_CHECKING` is recognized by shape**: `if TYPE_CHECKING:` and `if <anything>.TYPE_CHECKING:`. An alias (`if TC:`), a negation (`if not TYPE_CHECKING:`) or a compound condition is not recognized, and neither is the `else:` branch; those imports keep the surrounding timing.
- **`__lazy_modules__`** is recognized only as an assignment in the module body itself, whose value is a list, tuple or set literal of strings. It applies to the imports after it, as in Python 3.15, whose rules it follows: a plain import is lazy if the module it names (`a.b` for `import a.b`, the resolved `from` module for `from ... import ...`) is listed, unless it is a star import or sits in a class body, a `try` body or an `except` handler. Other assignments (`+=`, a non-literal value) are ignored with a warning; mutations and assignments nested in a block are ignored silently. Such imports count as `'top'`.
- **Lazy imports are classified from the source**, not by the Python version running pytest: an import covered by `__lazy_modules__` is `'lazy'` even on Python 3.11. Process-wide switches such as `-X lazy_imports=all` are runtime configuration and are not considered.
- **`lazy` syntax needs Python 3.15 to parse.** On older versions, a file using it fails to parse and is skipped, so rules over it would pass silently. When the parse error is on a `lazy import` line, the plugin also emits a `UserWarning`; run pytest on Python 3.15+ to check such files.
- `must_alias` does not take `timing=`; the alias rule is the same wherever the import runs.

### Performance

The model is built once per test session, so each test only pays for evaluating its rules, which takes well under a millisecond for most rules. Building the model is linear in the size of the source tree. For reference, the in-repo benchmark against Django 5.2 (~2,800 modules, ~18,000 import statements) builds the model in **~2.2 s** on a modern laptop. Even the most expensive project-wide rule, `must_not_import(internal(), via='absolute')`, which scans every import, takes **~40 ms**. See `benchmark/` and `uv run nox -s benchmark`.

### Configuration

The plugin determines the source roots as follows:

1. If `imports_project_paths` is set in the pytest config, use that.
2. Otherwise, walk up from pytest's rootpath to find `pyproject.toml`, `setup.cfg` or `setup.py`.
3. If a `src/` directory exists next to that file, use `src/`. A sibling `test/` or `tests/` directory is then *not* part of the model or of `project()`.
4. Otherwise, use the directory containing that file. In a flat layout this typically *includes* `test/` or `tests/`.

The `imports_project_paths` fixture shows the resolved source roots. If they are not what you want (say, a flat layout without tests, or a `src/` layout plus `test/`), set `imports_project_paths` explicitly, or use a narrower scope such as `scope('myapp')` instead of `project()`:

```toml
[tool.pytest.ini_options]  # or [tool.pytest] with pytest 9.0+
imports_project_paths = ["src", "test"]
```
Any other config format that pytest supports works too.

Each entry should normally be an *import root*: the directory you would put on `sys.path`, such as `src/`. You may also point at a package directory (one with an `__init__.py`), such as `src/myapp`. Only that package is then analyzed, but its modules keep their full names (`myapp.core`, not `core`). Imports of sibling packages outside it then count as external rather than `internal()`.

- **Namespace packages:** a directory *without* `__init__.py` is always treated as an import root, because it is indistinguishable from a [namespace package](https://peps.python.org/pep-0420/). So don't point at a namespace package directly.
- **Duplicate or nested entries:** an entry that repeats another, or lies inside another, is skipped with a warning.

## Related Python libraries

- [import-linter](https://pypi.org/project/import-linter)
- [pytestarch](https://pypi.org/project/pytestarch)
- [pytest-archon](https://pypi.org/project/pytest-archon)
- [pytest-importson](https://github.com/jwbargsten/pytest-importson)
- [findimports](https://pypi.org/project/findimports)
- [pydeps](https://pypi.org/project/pydeps) (based on bytecode, not AST)
- [modulefinder](https://docs.python.org/3/library/modulefinder.html) (standard library, looks at runtime)
- [archunitpython](https://pypi.org/project/archunitpython)

## License

Licensed under the Apache License, Version 2.0; see LICENSE.md in the project root directory.
