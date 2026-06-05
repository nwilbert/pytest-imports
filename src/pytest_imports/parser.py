import ast
import logging
from collections.abc import Generator, Sequence
from pathlib import Path

from .model import DotPath, ImportInModule, RootNode

log = logging.getLogger(__name__)


def build_import_model(base_paths: Sequence[Path]) -> RootNode:
    root_node = RootNode()
    for base_path in base_paths:
        for module_path, module_source in _walk_modules(base_path):
            try:
                module_ast = ast.parse(module_source, str(module_path))
            except SyntaxError as exc:
                log.warning(f'Skipping {module_path}: {exc}')
                continue
            dot_path = DotPath.from_path(module_path.relative_to(base_path))
            node = root_node.get_or_add(dot_path, module_path)
            imports = _collect_imports(module_ast, dot_path)
            if module_path.name == '__init__.py':
                node.add_data_for_init_file(imports)
            else:
                node.add_imports(imports)
    return root_node


def _collect_imports(
    module_ast: ast.Module, node_path: DotPath
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
                        )
                    )
            case ast.ImportFrom() as ast_import_from:
                for alias in ast_import_from.names:
                    if ast_import_from.module:
                        from_path = DotPath(ast_import_from.module)
                    else:
                        from_path = DotPath()
                    if (level := ast_import_from.level) > 0:
                        if level > len(node_path.parts):
                            log.warning(
                                f'Skipping import from {node_path} because '
                                f'relative import level goes beyond project.'
                            )
                            continue
                        else:
                            from_path = DotPath(node_path.parts[:-level]) / from_path
                    from_path /= alias.name
                    imports.append(
                        ImportInModule(
                            dot_path=from_path,
                            line_no=alias.lineno,
                            level=ast_import_from.level,
                        )
                    )
    return imports


def _walk_modules(base_path: Path) -> Generator[tuple[Path, bytes], None, None]:
    for path in base_path.glob('**/*.py'):
        relative_parts = path.relative_to(base_path).parts
        if any(part.startswith('.') for part in relative_parts):
            continue
        yield path, path.read_bytes()
