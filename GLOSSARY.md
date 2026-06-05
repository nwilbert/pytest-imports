# Glossary

This project commits to a single, consistent vocabulary for talking about
Python module structure and the rules we apply to it. Use these terms in
code, docstrings, error messages, specs, PR descriptions, and review
comments. When introducing a new domain term, add it here in the same
change.

We follow the
[language reference](https://docs.python.org/3/reference/import.html)
as the strongest source: a `submodule` is any module that is a direct
child of a package — `.py` files **and** subpackages both qualify. A
`subpackage` is the special case of a submodule that is itself a package.
For the transitive notion ("nested at any depth") we use `descendant`,
which is a project term, not Python's.

The [glossary's `package` entry](https://docs.python.org/3/glossary.html#term-package)
and the [tutorial](https://docs.python.org/3/tutorial/modules.html#packages)
use these words less rigorously and can read as if `submodule` and
`subpackage` were disjoint; we defer to the language reference.

## Module structure

- **module** — A Python module. May be a single `.py` file or a package
  directory containing `__init__.py`. The top-level entity in our model.
  See Python glossary:
  [module](https://docs.python.org/3/glossary.html#term-module).
- **package** — A module backed by a directory with `__init__.py`. Every
  package is a module; not every module is a package. See Python glossary:
  [package](https://docs.python.org/3/glossary.html#term-package) and
  [regular package](https://docs.python.org/3/glossary.html#term-regular-package).
- **submodule** — A module that is a direct child of a package. Both
  `.py` files and subpackages qualify: `a/b.py` makes `a.b` a submodule
  of `a`, and `a/b/__init__.py` also makes `a.b` a submodule of `a`. By
  itself "submodule" carries no claim about file vs directory; use
  `subpackage` when you specifically mean the package case. Matches the
  Python
  [language reference](https://docs.python.org/3/reference/import.html#submodules).
- **subpackage** — A submodule that is itself a package. `a/b/__init__.py`
  makes `a.b` a subpackage of `a`. Every subpackage is a submodule; not
  every submodule is a subpackage. See Python glossary:
  [package](https://docs.python.org/3/glossary.html#term-package).
- **descendant** — A module nested under a given module at **any** depth.
  `a.b` and `a.b.c` are both descendants of `a`; only `a.b` is a submodule
  of `a`. Every submodule is a descendant; not every descendant is a
  submodule. Rules like `must_import('a.b')` apply to `a.b` and all its
  descendants. Not a Python documentation term; specific to this project,
  introduced to name the transitive relation crisply.

## Imports

- **dot path** — *Project term.* A dotted path used to identify a module
  or import target, e.g. `foo.bar.baz`. Backed by the `DotPath` type
  (`src/pytest_imports/model.py`). Attributes named `dot_path` on the
  public dataclasses (`ModuleNode.dot_path`, `ImportInModule.dot_path`)
  always carry a *fully qualified* absolute value — even when the source
  statement is a relative import, in which case the relativity is
  recorded separately by `level > 0`. Internal helpers may construct
  `DotPath` instances that are relative or empty; see the `DotPath`
  class docstring.

  Python's
  [glossary uses *"import path"*](https://docs.python.org/3/glossary.html#term-import-path)
  for a completely different concept — the *search path*, a list of
  filesystem locations like `sys.path`. We avoid the term *"import path"*
  for that reason. Python's term for what our `dot_path` carries is
  *qualified (module) name* or *dotted module name*.
- **absolute import** — `import foo.bar` or `from foo.bar import x`. The
  source statement carries no leading dots; `ImportInModule.level == 0`.
  See [PEP 328](https://peps.python.org/pep-0328/).
- **relative import** — `from . import x` or `from ..bar import x`. In our
  model, `ImportInModule.level > 0`. See Python reference:
  [Package relative imports](https://docs.python.org/3/reference/import.html#package-relative-imports)
  and [PEP 328](https://peps.python.org/pep-0328/).
- **internal import** — An import whose target resolves inside the
  configured project source paths.
- **external import** — An import whose target is the standard library or
  an installed third-party package.
- **private name** — Any dotted-path part beginning with `_` (single or
  double underscore), with the sole exception of `__future__`.

## Rule vocabulary

- **scope** — The set of modules a rule applies to. Created via `scope(...)`,
  the bare string form (`'foo'`), or `project()` for the whole project.
- **predicate** — A rule object (`MustImport`, `MustNotImport`,
  `MustNotImportPrivate`, …) applied to a scope. Built via factory
  functions like `must_import` and `must_not_import`.
- **target** — An import target selector accepted by `must_import` and
  `must_not_import`: a dotted path string, or one of the helpers
  `descendants(p)` (descendants of `p`, excluding `p` itself) or
  `internal()` (any module under the configured source roots).
- **project** — The full set of modules under the configured source
  roots. Returned by `project()` as a special scope. Whether this
  includes a `test/` or `tests/` directory depends on layout: with a
  `src/` layout the auto-detected source root is `src/` (tests excluded);
  with a flat layout the source root falls back to the directory
  containing `pyproject.toml` (tests included). See the
  [Configuration](../README.md#configuration) section of the README for
  the full resolution logic and how to override it.
- **source root** — A directory configured as a project source path. The
  modules under a source root form the "project" walked by `project()`.
  Resolved from `imports_project_paths` in the pytest config, or
  auto-detected (see README's *Configuration* section). Exposed at test
  time by the `imports_project_paths` fixture.
