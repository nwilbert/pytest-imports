
# pytest-imports

*A pythonic derivative of [ArchUnit](https://www.archunit.org), in the form of a [pytest](https://www.pytest.org) plugin.*

The idea is to write automated tests for the architecture aspects of your Python project. This plugin specifically covers import statements in your Python code, enabling you to check the dependencies in your project.

### Simple example
```python
from pytest_imports import must_import, must_not_import

def test_imports(imports):
    imports.check({
        'foo': must_import('bar'),
        'baz': must_not_import('qux'),
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

```python
from pytest_imports import must_import, must_not_import, scope

def test_layered_architecture(imports):
    imports.check({
        scope('myapp', without='api'): must_not_import('myapp.api'),
        'myapp.api':                   must_import('myapp.core'),
    })
```
`scope('myapp', without='api')` covers all of `myapp` except `myapp.api` and its descendants. The excluded name can be a subpackage (`api/`) or a `.py` module file (`plugin.py`) — anything that appears as a direct or nested name in the tree. Pass a list to exclude multiple paths: `without=['api', 'adapters']`.

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
            must_not_import('sqlalchemy'),
            must_not_import('flask'),
        ],
    })
```
A list of predicates can be used to apply multiple rules to the same scope. All failures are reported together rather than stopping at the first violation.

```python
from pytest_imports import must_not_import_private, project

def test_no_private_imports(imports):
    imports.check({
        project(): must_not_import_private(),
    })
```
`must_not_import_private()` checks that no module imports a private symbol — any name starting with `_` or `__`, except the standard `__future__` module. `project()` is a special scope covering all modules under the configured source root — see [Configuration](#configuration) for which paths that includes (notably, with a `src/` layout `project()` does *not* include test folders, but with a flat layout it does). You can restrict to a specific package with `must_not_import_private('myapp')`.

```python
from pytest_imports import must_not_import_within_parent, project

def test_intra_package_imports_are_relative(imports):
    imports.check({
        project(): must_not_import_within_parent(via='absolute'),
    })
```
`must_not_import_within_parent(via='absolute')` checks that no module uses an absolute import to import from its own (immediate parent) package. For example, if `myapp.core.bbb` imports `myapp.core.aaa`, it must use `from .aaa import ...` rather than `from myapp.core.aaa import ...`. The `via` argument is required: use `via='absolute'` to enforce relative imports for intra-package dependencies, or `via='relative'` to enforce the opposite.

Note: This is similar to ruff's [TID252 (relative-imports)](https://docs.astral.sh/ruff/rules/relative-imports/#relative-imports-tid252) rule, but works in the opposite direction — TID252 bans relative imports in favor of absolute ones, while `must_not_import_within_parent(via='absolute')` bans absolute intra-package imports in favor of relative ones.

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
