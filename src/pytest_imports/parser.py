from __future__ import annotations

import ast
import logging
import re
import sys
import warnings
from collections.abc import Generator, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .model import DotPath, ImportInModule, RootNode, Timing

log = logging.getLogger(__name__)

# Module-level so tests can monkeypatch it on any interpreter.
_HAS_LAZY_SYNTAX = sys.version_info >= (3, 15)
_LAZY_IMPORT_LINE = re.compile(rb'^\s*lazy\s+(import|from)\s', re.MULTILINE)


def build_import_model(base_paths: Sequence[Path]) -> RootNode:
    root_node = RootNode()
    for base_path in _outermost_source_roots(base_paths):
        package_prefix = _package_prefix(base_path)
        for module_path, module_source in _walk_modules(base_path):
            try:
                with warnings.catch_warnings():
                    # We are inspecting potentially-broken user code; warnings
                    # like SyntaxWarning ("invalid decimal literal") or
                    # DeprecationWarning emitted during parse are not actionable
                    # by callers of this plugin.
                    warnings.simplefilter('ignore')
                    module_ast = ast.parse(module_source, str(module_path))
            except SyntaxError as exc:
                log.warning(f'Skipping {module_path}: {exc}')
                if not _HAS_LAZY_SYNTAX and _LAZY_IMPORT_LINE.search(module_source):
                    # Logged skips are hidden for passing tests, and every
                    # rule over this file would pass; make it visible.
                    warnings.warn(
                        f'Skipping {module_path}: it uses PEP 810 lazy imports, '
                        f'which need Python 3.15+ to parse. Run pytest on '
                        f'Python 3.15 or newer to check its imports.',
                        UserWarning,
                        stacklevel=2,
                    )
                continue
            dot_path = package_prefix / DotPath.from_path(
                module_path.relative_to(base_path)
            )
            node = root_node.get_or_add(dot_path, module_path)
            is_init = module_path.name == '__init__.py'
            package_path = dot_path if is_init else dot_path.parent
            imports = _collect_imports(module_ast, package_path, module_path)
            if is_init:
                node.add_data_for_init_file(module_path, imports)
            else:
                node.add_imports(imports)
    return root_node


def _outermost_source_roots(base_paths: Sequence[Path]) -> list[Path]:
    """Drop source roots that repeat or lie inside another source root.

    Walking both would add the same modules twice under the same dot paths.
    """
    resolved = [(path, path.resolve()) for path in base_paths]
    roots: list[Path] = []
    for i, (path, resolved_path) in enumerate(resolved):
        outer = next(
            (
                other
                for j, (other, resolved_other) in enumerate(resolved)
                if resolved_other in resolved_path.parents
                or (resolved_other == resolved_path and j < i)
            ),
            None,
        )
        if outer is not None:
            log.warning(f'Skipping {path}: it lies inside source root {outer}.')
            continue
        roots.append(path)
    return roots


def _package_prefix(base_path: Path) -> DotPath:
    """Return the dotted name of `base_path` if it is a package, else empty.

    A source root is normally an import root (a `sys.path` entry like
    `src/`). If it is a package directory instead, its modules are named
    relative to the nearest ancestor that is not a package, so they keep
    their real dotted names.
    """
    names: list[str] = []
    path = base_path.resolve()
    while (path / '__init__.py').is_file() and path.parent != path:
        names.append(path.name)
        path = path.parent
    return DotPath(tuple(reversed(names)))


def _collect_imports(
    module_ast: ast.Module, package_path: DotPath, module_path: Path
) -> Sequence[ImportInModule]:
    return _ImportCollector(package_path, module_path).collect(module_ast)


class _ImportCollector:
    """Collects the imports of one module in source order, with their timing.

    A recursive descent over the statements carries a `_Context` down the
    tree. Expression subtrees are skipped, since imports are statements.
    """

    def __init__(self, package_path: DotPath, module_path: Path) -> None:
        self._package_path = package_path
        self._module_path = module_path
        self._imports: list[ImportInModule] = []
        # Statement modules named by the `__lazy_modules__` assignment in
        # effect at the current statement.
        self._lazy_modules: frozenset[str] = frozenset()

    def collect(self, module_ast: ast.Module) -> list[ImportInModule]:
        for stmt in module_ast.body:
            self._update_lazy_modules(stmt)
            self._visit(stmt, _Context())
        return self._imports

    def _update_lazy_modules(self, stmt: ast.stmt) -> None:
        # Only assignments in the module body itself are recognized; each
        # replaces the set for all statements after it, as in CPython.
        match stmt:
            case ast.Assign(targets=targets, value=value) if any(
                _is_lazy_modules_name(target) for target in targets
            ):
                names = _string_set_literal(value)
            case ast.AnnAssign(target=target, value=ast.expr() as value) if (
                _is_lazy_modules_name(target)
            ):
                names = _string_set_literal(value)
            case ast.AugAssign(target=target) if _is_lazy_modules_name(target):
                names = None
            case _:
                return
        if names is None:
            log.warning(
                f'Ignoring __lazy_modules__ assignment in {self._module_path}, '
                f'line {stmt.lineno}: only a list, tuple or set literal of '
                f'strings is recognized.'
            )
            return
        self._lazy_modules = names

    def _visit(self, node: ast.AST, ctx: _Context) -> None:
        match node:
            case ast.Import():
                self._add_import(node, ctx)
            case ast.ImportFrom():
                self._add_import_from(node, ctx)
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
            # Only promotes from 'top': function wins, and nested
            # TYPE_CHECKING blocks keep their timing through the default arm.
            case ast.If() if ctx.timing == 'top' and _is_type_checking(node.test):
                self._visit_all(node.body, replace(ctx, timing='type_checking'))
                self._visit_all(node.orelse, ctx)
            case _:
                self._visit_children(node, ctx)

    def _visit_children(self, node: ast.AST, ctx: _Context) -> None:
        self._visit_all(
            (
                child
                for child in ast.iter_child_nodes(node)
                if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case))
            ),
            ctx,
        )

    def _visit_all(self, nodes: Iterable[ast.AST], ctx: _Context) -> None:
        for node in nodes:
            self._visit(node, ctx)

    def _add_import(self, node: ast.Import, ctx: _Context) -> None:
        for alias in node.names:
            self._imports.append(
                ImportInModule(
                    dot_path=DotPath(alias.name),
                    line_no=alias.lineno,
                    asname=alias.asname,
                    # The statement module of `import a.b` is `a.b`.
                    timing=self._timing(node, alias.name, ctx),
                )
            )

    def _add_import_from(self, node: ast.ImportFrom, ctx: _Context) -> None:
        from_path = DotPath(node.module) if node.module else DotPath()
        if (level := node.level) > 0:
            anchor_depth = len(self._package_path.parts) - (level - 1)
            # A relative import must anchor to at least the
            # top-level package; Python raises ImportError otherwise.
            if anchor_depth < 1:
                log.warning(
                    f'Skipping relative import in {self._module_path}, '
                    f'line {node.lineno}: it goes beyond the '
                    f'top-level package.'
                )
                return
            from_path = DotPath(self._package_path.parts[:anchor_depth]) / from_path
        # The statement module is the resolved absolute `from` module.
        timing = self._timing(node, str(from_path), ctx)
        for alias in node.names:
            self._imports.append(
                ImportInModule(
                    dot_path=from_path / alias.name,
                    line_no=alias.lineno,
                    level=node.level,
                    asname=alias.asname,
                    is_from_import=True,
                    timing=timing,
                )
            )

    def _timing(
        self, node: ast.Import | ast.ImportFrom, statement_module: str, ctx: _Context
    ) -> Timing:
        # Priority: function > type_checking > lazy > top.
        if ctx.timing != 'top':
            return ctx.timing
        # `is_lazy` exists only from Python 3.15 on.
        if getattr(node, 'is_lazy', 0):
            return 'lazy'
        if (
            ctx.lazy_eligible
            and statement_module in self._lazy_modules
            and not any(alias.name == '*' for alias in node.names)
        ):
            return 'lazy'
        return 'top'


@dataclass(frozen=True)
class _Context:
    # 'top', 'function' or 'type_checking'; 'lazy' is decided per statement.
    timing: Timing = 'top'
    # False where CPython ignores `__lazy_modules__`: class bodies, `try`
    # bodies and `except` handlers.
    lazy_eligible: bool = True


def _is_type_checking(test: ast.expr) -> bool:
    # Shape-based: `TYPE_CHECKING` or `<anything>.TYPE_CHECKING`. Aliases,
    # negations and compound conditions are not recognized.
    match test:
        case ast.Name(id='TYPE_CHECKING') | ast.Attribute(attr='TYPE_CHECKING'):
            return True
    return False


def _is_lazy_modules_name(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == '__lazy_modules__'


def _string_set_literal(value: ast.expr) -> frozenset[str] | None:
    """Return the strings of a list, tuple or set literal of string constants."""
    match value:
        case ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts):
            names = [
                elt.value
                for elt in elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            if len(names) == len(elts):
                return frozenset(names)
    return None


def _walk_modules(base_path: Path) -> Generator[tuple[Path, bytes], None, None]:
    for path in base_path.glob('**/*.py'):
        relative_parts = path.relative_to(base_path).parts
        if any(part.startswith('.') for part in relative_parts):
            continue
        if path.name != '__init__.py' and path.with_suffix('').is_dir():
            # Python prefers the package when `pkg/sub.py` and `pkg/sub/`
            # coexist; skip the file so both don't share one node.
            log.warning(
                f'Skipping {path}: a package of the same name exists alongside it.'
            )
            continue
        yield path, path.read_bytes()
