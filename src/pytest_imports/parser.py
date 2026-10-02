import ast
import logging
import warnings
from collections.abc import Generator, Sequence
from pathlib import Path

from .model import DotPath, ImportInModule, RootNode

log = logging.getLogger(__name__)


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
    imports: list[ImportInModule] = []
    for ast_node in ast.walk(module_ast):
        match ast_node:
            case ast.Import() as ast_import:
                for alias in ast_import.names:
                    imports.append(
                        ImportInModule(
                            dot_path=DotPath(alias.name),
                            line_no=alias.lineno,
                            asname=alias.asname,
                        )
                    )
            case ast.ImportFrom() as ast_import_from:
                if ast_import_from.module:
                    from_path = DotPath(ast_import_from.module)
                else:
                    from_path = DotPath()
                if (level := ast_import_from.level) > 0:
                    anchor_depth = len(package_path.parts) - (level - 1)
                    # A relative import must anchor to at least the
                    # top-level package; Python raises ImportError otherwise.
                    if anchor_depth < 1:
                        log.warning(
                            f'Skipping relative import in {module_path}, '
                            f'line {ast_import_from.lineno}: it goes beyond the '
                            f'top-level package.'
                        )
                        continue
                    from_path = DotPath(package_path.parts[:anchor_depth]) / from_path
                for alias in ast_import_from.names:
                    imports.append(
                        ImportInModule(
                            dot_path=from_path / alias.name,
                            line_no=alias.lineno,
                            level=ast_import_from.level,
                            asname=alias.asname,
                            is_from_import=True,
                        )
                    )
    return imports


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
