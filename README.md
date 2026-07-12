
# pytest-imports

*A pythonic derivative of [ArchUnit](https://www.archunit.org), in the form of a [pytest](https://www.pytest.org) plugin.*

The idea is to write automated tests for the architecture aspects of your Python project. This plugin specifically covers import statements in your Python code, enabling you to check the dependencies in your project.

### Simple example
```python
from pytest_imports import must_import, must_not_import, scope

def test_imports(imports):
    imports.check({
        scope('foo'): must_import('bar'),
        scope('baz'): must_not_import('qux'),
    })
```
This checks that module `foo` imports `bar`, and that module `baz` does not import `qux`.

Both `must_import` and `must_not_import` are inclusive with regards to descendants
(i.e., if there is an import of `foo.foo2` in a descendant `bar.bar2` then the rule is satisfied).
See [Terminology](#terminology) for what we mean by *descendant*, *submodule*, and *subpackage*.

### Installation & use

Install `pytest-imports` via the Python package manager of your choice (e.g., pip or uv).

If your project structure is "normal" then you can simply start using the `imports` fixture in your tests right away, as seen above.

### Complex examples
Dot paths in rules are always specified as fully qualified absolute paths (using `.` as separator). See [Terminology](#terminology) and [GLOSSARY.md](GLOSSARY.md) for the project's vocabulary.

Quick reference of the building blocks used below:

| Name | Kind | Purpose |
|---|---|---|
| [`scope(path)`](#example-layered) | scope | Restrict a rule to `path` and its descendants. |
| [`scope(path, without=...)`](#example-layered) | scope | Same, but exclude named submodules or subpackages. |
| [`project()`](#example-private) | scope | All modules under the configured source roots. |
| [`must_import(target)`](#example-layered) | predicate | Require an import of `target` (or a descendant) in scope. Accepts a list of targets (all required). |
| [`must_not_import(target)`](#example-layered) | predicate | Forbid imports of `target` (or a descendant) in scope. Accepts a list of targets (any forbidden). |
| [`must_only_import(allowed, among=internal())`](#example-only) | predicate | Allow only the listed targets within `among`; anything else inside `among` is a violation. |
| [`must_not_import_private(target=None)`](#example-private) | predicate | Forbid imports of any private (`_`-prefixed) name; an optional target filter narrows which private imports are flagged. |
| [`must_alias(path, alias)`](#example-alias) | predicate | Require that `path`, when it enters the namespace, does so only under `alias` (e.g. `numpy as np`). |
| [`descendants(path, without=...)`](#example-descendants) | target | Match descendants of `path` but not `path` itself; `without=` carves out subtrees. |
| [`internal()`](#example-internal) | target | Match any import resolving inside the source roots. |
| [`via='absolute'` / `via='relative'`](#example-via) | option | Restrict a predicate to one import style. |

<a id="example-layered"></a>
```python
from pytest_imports import must_import, must_not_import, scope

def test_layered_architecture(imports):
    imports.check({
        scope('myapp', without='api'): must_not_import('myapp.api'),
        scope('myapp.api'): must_import('myapp.core'),
    })
```
`scope('myapp', without='api')` covers all of `myapp` except `myapp.api` and its descendants. The excluded name can be a subpackage (`api/`) or a `.py` module file (`plugin.py`) — anything that appears as a direct or nested name in the tree. Pass a list to exclude multiple paths: `without=['api', 'adapters']`. Each entry can also be a dotted path into a deeper subtree, e.g. `without='db.migrations'` excludes only `myapp.db.migrations` (and its descendants) while leaving the rest of `myapp.db` in scope.

<a id="example-via"></a>
```python
def test_no_relative_imports_in_public_api(imports):
    imports.check({
        scope('myapp.api'): must_not_import('myapp', via='relative'),
    })
```
Via the `via` argument you can restrict a rule to only absolute (`via='absolute'`) or only relative (`via='relative'`) imports. Omitting `via` matches both.

```python
def test_multiple_rules_per_scope(imports):
    imports.check({
        scope('myapp', without=['adapters']): [
            must_not_import(['sqlalchemy', 'flask']),
            must_import('myapp.core'),
        ],
    })
```
A predicate accepts a list of targets, so a fan-out of "forbid each of these" collapses to one `must_not_import(['sqlalchemy', 'flask'])` — disjunctive, so an import of either is a violation, and the failure message names which one matched. `must_import([...])` is conjunctive: every listed target must be imported somewhere in scope. A list of *predicates* (as above) applies several different rules to the same scope; all failures are reported together rather than stopping at the first violation.

<a id="example-only"></a>
```python
from pytest_imports import must_only_import, scope

def test_api_layer_imports(imports):
    imports.check({
        scope('myapp.api'): must_only_import(['myapp.core', 'myapp.schemas']),
    })
```
`must_only_import` is the allowlist complement of `must_not_import`: within a bounded universe of imports, only the listed targets are permitted, and anything else inside that universe is a violation. The universe is the `among` parameter, which defaults to `internal()` — so the rule above says "`myapp.api` may only reach into `myapp.core` and `myapp.schemas`," while leaving stdlib and third-party imports (`os`, `fastapi`, …) untouched because they fall outside `internal()`. Each `allowed` entry is a [target](#example-descendants), so `descendants(...)` and `internal()` work there too, and a single target may be passed without the list. Override `among` to widen or narrow the universe, e.g. `among=descendants('myapp')` to police only `myapp.*` imports. An empty allowlist (`must_only_import([])`) forbids every import within `among` — a guardrail for a leaf module that must not reach back into the project.

<a id="example-private"></a>
```python
from pytest_imports import must_not_import_private, project

def test_no_private_imports(imports):
    imports.check({
        project(): must_not_import_private(),
    })
```
`must_not_import_private()` checks that no module imports a private name — any dotted-path part starting with `_` or `__`, except the standard `__future__` module. `project()` is a special scope covering all modules under the configured source root — see [Configuration](#configuration) for which paths that includes (notably, with a `src/` layout `project()` does *not* include test folders, but with a flat layout it does). The optional argument is a [target](#example-descendants) (or list of targets) that filters which private imports are flagged: `must_not_import_private('myapp')` restricts to a specific package, `must_not_import_private(internal())` flags only private imports of project-internal names (leaving third-party `_`-prefixed imports alone), and `must_not_import_private(descendants('myapp.capture'))` narrows to a subtree.

<a id="example-alias"></a>
```python
from pytest_imports import must_alias, project

def test_numpy_alias(imports):
    imports.check({
        project(): must_alias('numpy', 'np'),
    })
```
`must_alias('numpy', 'np')` enforces a conventional import alias: whenever `numpy` would enter a module's namespace under any other name, the import is flagged. It rejects `import numpy` (binds the bare name), `import numpy as foo` (wrong alias), `import numpy.linalg` (Python binds the top-level `numpy`), and `import numpy.linalg as np` (the canonical alias pointing at a submodule), while accepting `import numpy as np` and `import numpy.linalg as nl`. Unlike `must_import`, it does **not** require `numpy` to be imported — it only constrains *how* it is imported when it appears. The rule is namespace-oriented, so from-imports of members and submodules (`from numpy import array`, `from numpy.linalg import inv`) are allowed because they don't bind `numpy` itself; a wildcard `from numpy import *` is flagged as namespace pollution.

<a id="example-descendants"></a>
```python
from pytest_imports import descendants, must_not_import, scope

def test_capture_internals_are_encapsulated(imports):
    imports.check({
        scope('myapp', without='capture'):
            must_not_import(descendants('myapp.capture')),
    })
```
`descendants('myapp.capture')` is a target helper that matches the descendants of `myapp.capture` (`myapp.capture.parser`, `myapp.capture.config`, …) but **not** `myapp.capture` itself. This lets the rest of `myapp` use the `myapp.capture` public surface (`import myapp.capture`) while keeping its internals private. A plain string target like `'myapp.capture'` would also flag `import myapp.capture`, which is usually not what you want here.

Pass `without=` to carve subtrees out of the match, interpreted relative to the path — `descendants('myapp.contrib', without='admin')` matches everything under `myapp.contrib` except `myapp.contrib.admin` and its descendants. It accepts the same shapes as `scope(without=...)`: a single string, a list (`without=['admin', 'gis']`), or a dotted nested path (`without='admin.widgets'`). This is the target-side mirror of `scope(path, without=...)`, and pairs naturally with [`must_only_import`](#example-only) to express "allow everything under X except Y".

<a id="example-internal"></a>
```python
from pytest_imports import internal, must_not_import, project

def test_internal_imports_are_relative(imports):
    imports.check({
        project(): must_not_import(internal(), via='absolute'),
    })
```
`internal()` is a target helper that matches every import whose target resolves to a module under the configured source roots. Combined with `via='absolute'` this enforces project-wide that all internal imports are written as relative imports — e.g. `from .aaa import ...` rather than `from myapp.core.aaa import ...`. Unlike a parent-package-only check, this also flags an absolute import of `myapp.other` from `myapp.core.bbb`.

Note: This is similar to ruff's [TID252 (relative-imports)](https://docs.astral.sh/ruff/rules/relative-imports/#relative-imports-tid252) rule, but works in the opposite direction — TID252 bans relative imports in favor of absolute ones, while `must_not_import(internal(), via='absolute')` bans absolute internal imports in favor of relative ones.

### Reporting violations without failing

For dashboards, ratchets, or benchmarks, use `imports.violations(rules)` instead of `imports.check(rules)`. It accepts the same rules dictionary and returns the list of violation messages without raising:

```python
def test_track_legacy_couplings(imports):
    failures = imports.violations({
        scope('myapp.api'): must_not_import('myapp.legacy'),
    })
    print(f'{len(failures)} legacy coupling(s) remain')
```

`check()` is `violations()` plus an `AssertionError` on non-empty output, so both report the same messages.

## Details

### Terminology

This project keeps a deliberate, consistent vocabulary — see
[GLOSSARY.md](GLOSSARY.md) for the full list. The most important
distinctions:

- **submodule** of `X` — a module that is a direct child of package `X`;
  both `.py` files and subpackages qualify.
- **subpackage** of `X` — a submodule of `X` that is itself a package.
  Every subpackage is a submodule.
- **descendant** of `X` — a module nested under `X` at *any* depth.
  `a.b.c` is a descendant of `a` but only a submodule of `a.b`.

Rules like `must_import('a.b')` and `must_not_import('a.b')` apply to
`a.b` and all its descendants.

### How it works

This plugin uses the `ast` module from the standard library to analyze the abstract syntax tree of your project. Import statements are collected and normalized when the `imports` fixture is first used in a test session.

The analysis is superficial, so there are limitations. Due to the dynamic nature of Python it is easy to circumvent tests if you want to. So we assume that this plugin is used in a "friendly" context.

Note that we don't track how the imported symbols are used. For example, in the case of
```python
import a
...
a.b()
```
you will *not* be able to check that `a.b` is used (e.g., via `must_import('a.b')`).

### Performance

The model is built once per test session (the `imports` fixture is session-scoped), so per-test cost is essentially the cost of evaluating the rules — well under a millisecond for most rules. Building the model is linear in the size of the source tree: as a reference point, the in-repo benchmark against the full Django 5.2 source tree (~2,800 modules, ~18,000 import statements) builds the model in **~2.7 s** on a modern laptop, and even the most expensive project-wide rule (`must_not_import(internal(), via='absolute')`, scanning every import in the project) completes in **~45 ms**. See `benchmark/` and `uv run nox -s benchmark` for the full suite.

### Absolute vs. relative imports

Dot paths in rules are always specified as fully qualified absolute paths, regardless of whether relative imports are used in the source. You can optionally use the `via` argument to distinguish between absolute and relative imports.

Note that relative imports from outside the configured project source directory are not supported (because we can't normalize those).

### Internal vs. external imports

Both imports from inside your project and from external packages (standard library or installed packages) are supported.

### Configuration

This plugin uses a simple heuristic to determine the source root of your project:

1. If `imports_project_paths` is set in the pytest config, use that.
2. Otherwise, walk up from pytest's rootpath looking for `pyproject.toml`, `setup.cfg`, or `setup.py`.
3. If a `src/` directory exists next to that config file, use `src/` — this excludes a sibling `test/` or `tests/` directory from the model, so `project()` covers source code only.
4. Otherwise fall back to the directory containing the config file — which in a flat layout typically *includes* `test/` or `tests/` in the model, and therefore in `project()`.

You can check the resolved source root via the `imports_project_paths` fixture in a test. If the auto-detected scope is not what you want — for example, you have a flat layout but want to exclude tests, or your project uses `src/` but you also want to apply rules to `test/` — set `imports_project_paths` explicitly, or use a narrower scope such as `scope('myapp')` instead of `project()`.

To specify the source root in the pytest configuration, if you use a `pyproject.toml` then this looks like:
```
[tool.pytest.ini_options]
    imports_project_paths = [
        "foo/bar",
    ]
```
With pytest 9.0+ you can also use the native TOML table:
```
[tool.pytest]
    imports_project_paths = [
        "foo/bar",
    ]
```
Other config formats are supported as well, as long as they are supported by pytest.

### Future plans

- Add and finetune the available rule building blocks.
- Optimize the implementation with regards to speed.

## License
Licensed under the Apache License, Version 2.0 - see LICENSE.md in project root directory.

## Related Python libraries
- https://pypi.org/project/import-linter
- https://pypi.org/project/pytestarch
- https://pypi.org/project/pytest-archon
- https://github.com/jwbargsten/pytest-importson
- https://pypi.org/project/findimports
- https://pypi.org/project/pydeps (based on bytecode, not AST)
- https://docs.python.org/3/library/modulefinder.html (part of standard library, looks at runtime)
- https://pypi.org/project/archunitpython
