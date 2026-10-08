# AGENTS.md

This file provides guidance to AI agents working with code in this repository.

See [README.md](README.md) for the full API reference and usage examples.

## Terminology

This project maintains a ubiquitous language in [GLOSSARY.md](GLOSSARY.md).
Use those terms — `module`, `package`, `submodule`, `subpackage`,
`descendant`, `scope`, `predicate`, etc. — consistently in code,
docstrings, error messages, specs, and PR descriptions. In particular,
treat `submodule` (a `.py` file in a package) and `subpackage` (a nested
package) as distinct, and use `descendant` as the umbrella term when the
distinction does not matter.

When you introduce a new domain term in code or docs, add it to
`GLOSSARY.md` in the same change.

## Commands

```bash
# Run all default nox sessions (format, lint, mypy, test, coverage, audit)
uv run nox

# Run a single nox session
uv run nox -s test              # tests with lockfile pytest version
uv run nox -s pytest_compat     # tests across Python + pytest version matrix (integration only)
uv run nox -s lint
uv run nox -s mypy
uv run nox -s coverage
uv run nox -s benchmark         # run the plugin against a pinned Django checkout and print timings

# Run tests directly (faster, no nox overhead)
uv run pytest

# Run a single test
uv run pytest test/unit/test_query.py::test_name

# Coverage with HTML report
uv run nox -s coverage -- html
```

## Architecture

The plugin registers itself via the `pytest11` entry point in `pyproject.toml`, pointing to `pytest_imports.plugin`.

**Data flow:**
1. `plugin.py` — pytest fixtures + `ImportsFixture.check()`. `imports_project_paths` resolves source roots; `imports_root_node` (session-scoped) builds the model once per session; `imports` wraps both.
2. `parser.py` — `build_import_model()` walks the filesystem with AST analysis to produce a `RootNode`. Source roots that repeat or nest inside another are dropped (`_outermost_source_roots`); a source root that is a package directory gets its dotted name as a prefix (`_package_prefix`), so module names are always relative to an import root. `_ImportCollector` collects each module's imports in source order by a depth-first walk over statements (an explicit stack, since long `elif` chains nest deeper than the recursion limit) that carries a `_Context` (enclosing timing, `__lazy_modules__` eligibility) and assigns each import its timing.
3. `model.py` — `RootNode` / `ModuleNode` (tree), `DotPath` (dot-separated path abstraction, pathlib-like), `ImportInModule` (single import record; `level > 0` means relative import; `timing` is one of `Timing = Literal['top', 'lazy', 'function', 'type_checking']`, defined here because both `parser` and `query` need it).
4. `query.py` — frozen dataclass predicates (`MustImport`, `MustNotImport`, `MustNotImportPrivate`, `MustOnlyImport`, `MustAlias`); target abstraction (`Target = str | Descendants | Internal | Stdlib | ThirdParty`) accepted by `must_import` / `must_not_import` / `must_only_import`; `Scope` (hashable dict key); factory functions exported from `__init__.py`; `evaluate_rules()` collects all failures before raising. `MustImport.path` / `MustNotImport.path` / `MustNotImportPrivate.path` are `tuple[Target, ...]` (the factories normalize a single target or list via `_as_target_tuple`; for the private predicate an empty tuple means "no filter"). `MustAlias(path, alias)` takes a single dotted-path string (not a target) plus the required alias. All predicates except `MustAlias` take `timing=`, normalized by `_as_timing_set` to a `frozenset[Timing]` (`None` = no filter; empty or unknown values raise `ValueError`).

**Key internals:**
- `scope(path, without=...)` stores exclusions as `tuple[str, ...]` for hashability.
- `MustImport` reports one failure per unsatisfied target (scope-level, not per `.py` file), conjunctive over its target tuple; `MustNotImport` is disjunctive — `_find_imports_matching_any` yields each import that matches any target (with the matched target, for the failure message), one failure per violating import line; `MustOnlyImport` walks `_find_matching_imports` filtered by `among` and applies the allowlist check inline.
- `_walk_imports` owns the scope walk plus the `via` / `timing` filters; `_find_imports_matching_any` (OR over a target tuple), `_find_matching_private_imports` and `_find_alias_violations` filter on top of it, and `_find_matching_imports` (single target) delegates to `_find_imports_matching_any`. Failure locations go through `_format_location`, which appends the actual timing when a rule names several.
- `project()` returns `Scope(path=None)`, which triggers `root_node.walk()` over all modules.
- `Internal`, `Stdlib` and `ThirdParty` partition every import: `_match_target` delegates to `_is_internal` (prefix walk over the model) and `_is_stdlib` (`sys.stdlib_module_names` on the top-level name), and internal wins over stdlib.
- `Descendants` may carry `without` exclusions (a `tuple[str, ...]`, relative to its `path`); they are evaluated in `_match_target`, which rejects any `dot_path` falling under an excluded subtree.
- `MustNotImportPrivate.path` is a `tuple[Target, ...]` (empty = no filter); `_find_matching_private_imports` OR-matches it via the `_match_target` family rather than the old `is_relative_to` string check, so `internal()` and `descendants(...)` work as private-import filters.
- `MustAlias` is namespace-oriented: `_find_alias_violations` walks imports whose `dot_path` is relative to `path` and delegates each to `_is_alias_violation`, which uses the new `ImportInModule.asname` / `is_from_import` fields — non-star from-imports are always OK (they bind only the member), a plain `import` must carry `asname == alias` on the target itself and must not bind `alias` to a descendant, and `from ... import *` is flagged.
- Timing priority is function > type_checking > lazy > top: once the descent enters a `def`, every import below is `'function'`; only the `body` of a recognized `if TYPE_CHECKING:` is `'type_checking'`. `_is_type_checking` is AST-shape based and deliberately narrow (`Name` or `Attribute` named `TYPE_CHECKING`; no aliases, negations or compound conditions).
- Lazy imports: the `lazy` keyword is read via `getattr(node, 'is_lazy', 0)` (the field exists only on 3.15+). `__lazy_modules__` is recognized only as a top-level literal assignment (`_update_lazy_modules`), matched against the statement module, and does not depend on the interpreter. On a SyntaxError whose line is a `lazy import` / `lazy from` statement (`_fails_at_lazy_import`), before 3.15 (`_HAS_LAZY_SYNTAX`, monkeypatchable), the parser also emits a `UserWarning`.
- Imports are collected in source order (not `ast.walk`'s breadth-first order), so failure messages follow line order.

**Test layout:**
- `test/unit/` — isolated unit tests (no filesystem)
- `test/integration/` — tests using real project files on disk
- `test/arch/` — self-referential architecture tests for this project
- `benchmark/` — performance benchmark against a pinned Django
  checkout; see `benchmark/conftest.py` for details. Run via
  `uv run nox -s benchmark`.

## Code organization

- Step-down rule: callers before callees, public before private. Read
  each file top-down from high-level API to implementation details.

## Documentation

- Always update AGENTS.md and README.md when making changes that affect commands, architecture, or usage.

## Verification

- Always run `uv run nox` after making changes to verify all sessions pass.

## Git

- Never add `Co-Authored-By` lines to commit messages.
