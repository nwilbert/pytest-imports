# Spec: `AbsoluteDotPath` subtype

## Status

Deferred. Not currently scheduled. Implement when:

- A bug is traced to absolute/relative `DotPath` confusion, **or**
- A new predicate is added that takes user-supplied paths and would
  benefit from a type-level guarantee at its boundary, **or**
- A contributor introduces internal helpers and there is no longer a
  single small file to keep the invariant in their head.

## Motivation

`DotPath` is currently a single type used in two distinct modes:

- **Fully qualified absolute paths** — `ModuleNode.dot_path`,
  `ImportInModule.dot_path`, the `target_path` built from a predicate's
  `path` in `query.py`, the resolved `from_path` after relativity is
  folded in by `parser.py`.
- **Relative or empty paths** — arguments to `RootNode.get` and
  `get_or_add` (relative to the receiver), `ModuleNode.walk(exclude=...)`,
  the intermediate `DotPath(parts[1:])` slices used to recurse into
  children, the empty sentinel returned by `DotPath()` and
  `DotPath.parent` of a one-part path.

Today the invariant — *fields named `dot_path` on public dataclasses are
absolute* — is enforced by convention (naming rule, docstring on
`DotPath`, glossary entry). The convention works for the current
contributor count but does not survive into type-checker output.
Introducing a subtype encodes the invariant in the type system and
catches mixing at mypy time.

## Approach

Introduce `AbsoluteDotPath` as a **real subclass** of `DotPath`. Reject
the `NewType` approach: `DotPath` methods like `.parent`, `__truediv__`,
and `from_path` return `DotPath`, and a `NewType` alias would force a
`cast()` after every chained call, which is noisy and tends to be
abandoned.

The subclass approach preserves the marker on chained operations by
overriding the return types of operations that preserve absoluteness:

| Operation                    | On `DotPath`                | On `AbsoluteDotPath`                                     |
| ---------------------------- | --------------------------- | -------------------------------------------------------- |
| `parent`                     | `DotPath`                   | `AbsoluteDotPath` (an absolute path's parent is absolute)|
| `__truediv__(other)`         | `DotPath`                   | `AbsoluteDotPath` (absolute / anything stays absolute)   |
| `__rtruediv__(other)`        | `DotPath`                   | **stays** `DotPath` (left operand wins — anything / abs is not absolute) |
| `from_path(filesystem_path)` | `DotPath` classmethod       | `AbsoluteDotPath` classmethod (parser always builds absolute paths from filesystem) |
| `is_relative_to(other)`      | unchanged (returns `bool`)  | unchanged                                                |

Note `parent` on an absolute one-part path returns `AbsoluteDotPath(())`
— the empty path remains the parent sentinel. The empty path is
considered absolute (it identifies the project root, not a relative
position), which keeps the recursion in `RootNode.get_or_add` honest if
those internal sites ever migrate.

## Boundary inventory

Concrete plan for which surfaces switch to `AbsoluteDotPath` and which
stay `DotPath`:

### Becomes `AbsoluteDotPath`

- `ImportInModule.dot_path`
- `ModuleNode.dot_path` (property return type, and the underlying
  `_dot_path` field)
- `ModuleNode._child_dotpath` and `RootNode._child_dotpath` return types
- `target_path` locals in `query.py` (`MustImport`, `MustNotImport`
  arms)
- `_find_matching_imports(target_path: AbsoluteDotPath, ...)` parameter
- `_find_within_parent_imports`: `parent = module_node.dot_path.parent`
  is `AbsoluteDotPath` after the override
- `_find_matching_private_imports`: `filter_path` is
  `AbsoluteDotPath | None`
- `parser._collect_imports`: the `from_path` built up after relativity
  resolution and the `DotPath(alias.name)` for plain `import` statements
- `build_import_model` / `RootNode.get_or_add(dot_path, file_path)` —
  this one takes an `AbsoluteDotPath` at the **public entry point** but
  internally recurses with relative slices (see next section)

### Stays `DotPath`

- `RootNode.get(dot_path)` and `ModuleNode.get(dot_path)` arguments
  during recursion — internal recursion uses `DotPath(parts[1:])` which
  is relative to the receiver
- `ModuleNode.walk(exclude=...)` — exclusions are stored relative to
  scope (see `query.py:98`)
- `DotPath(parts[1:])` slices used in `RootNode` / `ModuleNode` recursion
- `DotPath()` empty sentinel (when used as the "this node" marker in
  `walk`)
- All callers of `DotPath` from `Scope.without` (`query.py:98`) —
  exclusions are relative to the scope path

### Mixed: `RootNode.get_or_add`

This is the trickiest case. The **public** call (from `parser.py` and
`build_import_model`) passes an absolute path. The **internal**
recursion slices a part off and recurses with a relative remainder. Two
acceptable shapes:

1. Keep `get_or_add` signature as `DotPath`, accept that callers pass
   an `AbsoluteDotPath` (subtype) at the entry, and let the internal
   recursion stay typed as `DotPath`. Loses type info inside but is
   simple.
2. Split into a public `get_or_add(dot_path: AbsoluteDotPath, ...)`
   that immediately delegates to a private `_get_or_add_relative(
   relative: DotPath, ...)`. Cleaner but more surface area.

Default to shape (1) unless a use case justifies the split.

## Required code changes

### `src/pytest_imports/model.py`

- Define `class AbsoluteDotPath(DotPath)` with method overrides per the
  table above.
- Override `__init__` to ban a non-empty relative-by-convention
  construction? **No** — keep `__init__` shared. Absoluteness is a
  declaration at the call site, not a runtime check; we cannot inspect a
  bare `('foo', 'bar')` tuple and know whether it's meant to be
  absolute. Construction of `AbsoluteDotPath` is a *promise* the caller
  makes.
- Change `ModuleNode._dot_path: AbsoluteDotPath`, and the
  `dot_path` property return type to `AbsoluteDotPath`.
- Update `ImportInModule.dot_path: AbsoluteDotPath`.

### `src/pytest_imports/parser.py`

- `import_path=DotPath(alias.name)` → `dot_path=AbsoluteDotPath(alias.name)`
  in the `ast.Import` branch.
- The `from_path` after the level-resolution block is `AbsoluteDotPath`
  (it has been anchored at `node_path`, which is absolute, when the
  source was relative). Wrap the construction so the type is preserved
  end-to-end. The intermediate `DotPath(ast_import_from.module)` is
  *relative* until it's anchored — keep it as `DotPath` and only mint
  the `AbsoluteDotPath` after the level-resolution `if` block.

### `src/pytest_imports/query.py`

- `target_path = AbsoluteDotPath(predicate.path)` in the `MustImport`
  and `MustNotImport` arms.
- `_find_matching_imports(..., target_path: AbsoluteDotPath, ...)`.
- `_find_matching_private_imports`: `filter_path: AbsoluteDotPath | None`.

### `src/pytest_imports/__init__.py`

- Export `AbsoluteDotPath` alongside `DotPath`. Both are needed by
  consumers writing custom helpers.

## Tests

- `test/unit/model/test_dotpath.py` — add tests for:
  - `AbsoluteDotPath.parent` returns `AbsoluteDotPath`.
  - `AbsoluteDotPath / 'x'` returns `AbsoluteDotPath`.
  - `'x' / AbsoluteDotPath('a.b')` returns `DotPath` (not promoted).
  - `AbsoluteDotPath.from_path(...)` returns `AbsoluteDotPath`.
  - `isinstance(AbsoluteDotPath(...), DotPath)` is `True` (subtyping).
- A mypy-only test (or a `# type: ignore[assignment]` expectation in
  an existing test file) demonstrating that assigning a plain `DotPath`
  to an `AbsoluteDotPath` annotation is flagged.

## Docs

- `GLOSSARY.md` — add an `AbsoluteDotPath` bullet under the existing
  *dot path* entry, explaining the subtype's role and that the empty
  path is considered absolute (sentinel).
- `AGENTS.md` — add one sentence to the Terminology section: when
  introducing new functions that take or return a fully qualified
  dotted name, prefer `AbsoluteDotPath` to make the contract explicit.

## Non-goals / open questions

- **Runtime validation**: `AbsoluteDotPath(('not', 'really', 'absolute'))`
  cannot be rejected without a context the type does not carry.
  Construction is a contract, not a check. If we want runtime
  enforcement later, add an explicit constructor like
  `AbsoluteDotPath.from_parts_anchored_at(root, parts)` that takes the
  anchor explicitly.
- **Generic phantom types** (`DotPath[Absolute]` vs `DotPath[Relative]`)
  were considered and rejected: heavier syntax in every signature with
  no additional safety over the subclass.
- **Migrating internal recursion to `AbsoluteDotPath`** is not in scope
  here. The relative-slice pattern in `RootNode.get_or_add` and
  `ModuleNode.walk` is genuinely relative; forcing it to absolute would
  require carrying an explicit anchor through recursion, which is more
  work than the safety gain justifies in current code.
