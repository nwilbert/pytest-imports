import ast
from inspect import cleandoc
from pathlib import Path

import pytest

from pytest_imports.model import DotPath
from pytest_imports.parser import _collect_imports


def _collect_with_lazy_lines(source: str, lazy_lines: set[int]) -> list[tuple]:
    """Collect imports from `source`, marking the statements on `lazy_lines` lazy.

    Setting `is_lazy` on the in-memory tree, as Python 3.15 does for the
    `lazy` keyword, covers that path on interpreters that cannot parse it.
    """
    module_ast = ast.parse(cleandoc(source))
    for node in ast.walk(module_ast):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno in lazy_lines:
            node.is_lazy = 1
    imports = _collect_imports(module_ast, DotPath('pkg'), Path('pkg/m.py'))
    return [(str(i.dot_path), i.timing) for i in imports]


@pytest.mark.parametrize(
    ('source', 'lazy_lines', 'expected'),
    [
        ('import a', {1}, [('a', 'lazy')]),
        ('from a import b', {1}, [('a.b', 'lazy')]),
        ('import a\nimport b', {2}, [('a', 'top'), ('b', 'lazy')]),
        (
            """
            if x:
                import a
            """,
            {2},
            [('a', 'lazy')],
        ),
        (
            """
            if TYPE_CHECKING:
                import a
            """,
            {2},
            [('a', 'type_checking')],
        ),
        # Python rejects `lazy` inside functions when compiling; the
        # parser does not re-validate.
        (
            """
            def f():
                import a
            """,
            {2},
            [('a', 'function')],
        ),
    ],
)
def test_lazy_keyword_timing(source, lazy_lines, expected):
    assert _collect_with_lazy_lines(source, lazy_lines) == expected
