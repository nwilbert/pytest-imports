import logging
import sys
import warnings
from inspect import cleandoc
from pathlib import Path

import pytest

from pytest_imports.model import DotPath, ImportInModule
from pytest_imports.parser import build_import_model


def _create_project_on_disk(struct: dict[str, str | dict], current_path: Path):
    for key, value in struct.items():
        path = current_path / key
        match value:
            case dict():
                path.mkdir()
                _create_project_on_disk(value, path)
            case str():
                path.write_text(cleandoc(value))


@pytest.fixture
def project_path(project_structure: dict[str, str | dict], tmp_path: Path) -> Path:
    _create_project_on_disk(project_structure, tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ('project_structure', 'path', 'import_obj'),
    [
        (
            {'a': {'b': {'c.py': '...\nfrom .. import y'}}},
            'a.b.c',
            ImportInModule(
                dot_path=DotPath('a.y'), line_no=2, level=2, is_from_import=True
            ),
        ),
        (
            {'a': {'b.py': '...\n\nfrom .x import y'}},
            'a.b',
            ImportInModule(
                dot_path=DotPath('a.x.y'), line_no=3, level=1, is_from_import=True
            ),
        ),
    ],
)
def test_relative_import(project_path: Path, path: DotPath, import_obj):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath(path)).imports == [import_obj]


@pytest.mark.parametrize(
    ('project_structure', 'path', 'file'),
    [
        # Python: "attempted relative import beyond top-level package".
        ({'a': {'b.py': 'from ... import y'}}, 'a.b', 'a/b.py'),
        ({'a': {'b.py': 'from .. import y'}}, 'a.b', 'a/b.py'),
        ({'a': {'__init__.py': 'from .. import y'}}, 'a', 'a/__init__.py'),
        # Python: "attempted relative import with no known parent package".
        ({'a.py': 'from . import y'}, 'a', 'a.py'),
        ({'a.py': 'from .json import y'}, 'a', 'a.py'),
        # One warning per statement, not per imported name.
        ({'a.py': 'from . import x, y'}, 'a', 'a.py'),
    ],
)
def test_relative_import_beyond_top_level_package(project_path, path, file, caplog):
    base_node = build_import_model([project_path])
    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert 'beyond the top-level package' in warnings[0].msg
    assert f'{project_path / file}, line 1:' in warnings[0].msg
    assert base_node.get(DotPath(path)).imports == []


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a': {'__init__.py': 'import x'},
        }
    ],
)
def test_import_from_init(project_path):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath('a')).imports == [ImportInModule(DotPath('x'), 1)]


@pytest.mark.parametrize(
    ('project_structure', 'path', 'import_obj'),
    [
        (
            {'pkg': {'__init__.py': 'from . import y'}},
            'pkg',
            ImportInModule(
                dot_path=DotPath('pkg.y'), line_no=1, level=1, is_from_import=True
            ),
        ),
        (
            {'pkg': {'__init__.py': 'from .x import y'}},
            'pkg',
            ImportInModule(
                dot_path=DotPath('pkg.x.y'), line_no=1, level=1, is_from_import=True
            ),
        ),
        (
            {'pkg': {'sub': {'__init__.py': 'from . import y'}}},
            'pkg.sub',
            ImportInModule(
                dot_path=DotPath('pkg.sub.y'), line_no=1, level=1, is_from_import=True
            ),
        ),
        (
            {'pkg': {'sub': {'__init__.py': 'from .. import y'}}},
            'pkg.sub',
            ImportInModule(
                dot_path=DotPath('pkg.y'), line_no=1, level=2, is_from_import=True
            ),
        ),
    ],
)
def test_relative_import_in_init(project_path: Path, path: str, import_obj):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath(path)).imports == [import_obj]


@pytest.mark.parametrize(
    ('project_structure', 'path', 'import_obj'),
    [
        (
            {
                'a': {'b.py': 'import x'},
            },
            'a.b',
            ImportInModule(dot_path=DotPath('x'), line_no=1),
        ),
        (
            {'a': {'b': {'c.py': '...\nimport x as y'}}},
            'a.b.c',
            ImportInModule(dot_path=DotPath('x'), line_no=2, asname='y'),
        ),
    ],
)
def test_absolute_import(project_path: Path, path: DotPath, import_obj):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath(path)).imports == [import_obj]


@pytest.mark.parametrize(
    ('project_structure', 'path', 'import_obj'),
    [
        (
            {'a.py': 'import x'},
            'a',
            ImportInModule(DotPath('x'), 1, asname=None, is_from_import=False),
        ),
        (
            {'a.py': 'import x as y'},
            'a',
            ImportInModule(DotPath('x'), 1, asname='y', is_from_import=False),
        ),
        (
            {'a.py': 'import x.y'},
            'a',
            ImportInModule(DotPath('x.y'), 1, asname=None, is_from_import=False),
        ),
        (
            {'a.py': 'from x import y'},
            'a',
            ImportInModule(DotPath('x.y'), 1, asname=None, is_from_import=True),
        ),
        (
            {'a.py': 'from x import y as z'},
            'a',
            ImportInModule(DotPath('x.y'), 1, asname='z', is_from_import=True),
        ),
        (
            {'pkg': {'a.py': 'from . import y'}},
            'pkg.a',
            ImportInModule(
                DotPath('pkg.y'), 1, level=1, asname=None, is_from_import=True
            ),
        ),
        (
            {'a.py': 'from x import *'},
            'a',
            ImportInModule(DotPath('x.*'), 1, asname=None, is_from_import=True),
        ),
    ],
)
def test_asname_and_is_from_import_captured(project_path: Path, path: str, import_obj):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath(path)).imports == [import_obj]


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import x, y as z'}],
)
def test_chained_import_captures_each_alias(project_path: Path):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath('a')).imports == [
        ImportInModule(DotPath('x'), 1, asname=None, is_from_import=False),
        ImportInModule(DotPath('y'), 1, asname='z', is_from_import=False),
    ]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a.py': """
                try:
                    import foo
                except:
                    import bar
            """,
        }
    ],
)
def test_import_in_nested_block(project_path):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath('a')).imports == [
        ImportInModule(dot_path=DotPath('foo'), line_no=2),
        ImportInModule(dot_path=DotPath('bar'), line_no=4),
    ]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a': {
                'b.py': """
                    from .x import y
                    from .x.y import z as xyz
                """,
            },
            'x': {
                '__init__.py': """
                    import a
                """,
                'y.py': """
                    import a
                    import a.b as ab
                    from a.b import c
                """,
            },
        }
    ],
)
def test_project_structure_nodes(project_path: Path):
    node = build_import_model([project_path])
    assert len(node.get(DotPath('a')).imports) == 0
    assert node.get(DotPath('a'))._file_path == project_path / 'a'
    assert len(node.get(DotPath('a.b')).imports) == 2
    assert node.get(DotPath('a.b'))._file_path == project_path / 'a' / 'b.py'
    assert len(node.get(DotPath('x')).imports) == 1
    assert node.get(DotPath('x'))._file_path == project_path / 'x' / '__init__.py'
    assert len(node.get(DotPath('x.y')).imports) == 3
    assert node.get(DotPath('x.y'))._file_path == project_path / 'x' / 'y.py'


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a': {'b.py': 'import x', '.d': {'c.py': 'import x'}},
            '.m.py': 'import y',
        }
    ],
)
def test_hidden_dirs_and_files_are_excluded(project_path: Path):
    node = build_import_model([project_path])
    assert node.get(DotPath('a.b'))
    assert len(node.get(DotPath('a'))._children) == 1
    assert len(node._children) == 1


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a.py': '',
        }
    ],
)
def test_empty_file(project_path):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath('a')).imports == []


def test_dot_prefixed_ancestor_does_not_exclude_base_path(tmp_path: Path):
    """A dot-prefixed directory above the source root must not hide files inside it."""
    hidden_parent = tmp_path / '.hidden_parent'
    base = hidden_parent / 'project'
    base.mkdir(parents=True)
    (base / 'a.py').write_text('import x')
    node = build_import_model([base])
    assert node.get(DotPath('a')).imports == [ImportInModule(DotPath('x'), 1)]


def test_utf8_encoded_source_is_handled(tmp_path: Path):
    """Source files are read as UTF-8 regardless of the platform default."""
    (tmp_path / 'a.py').write_text(
        '# comment with non-ascii: éè中\nimport x\n', encoding='utf-8'
    )
    node = build_import_model([tmp_path])
    assert node.get(DotPath('a')).imports == [ImportInModule(DotPath('x'), 2)]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'pkg': {
                '__init__.py': '',
                'sub.py': 'import collision_module',
                'sub': {'__init__.py': 'import package_import'},
            }
        }
    ],
)
def test_package_shadows_same_named_module(project_path: Path, caplog):
    with caplog.at_level(logging.WARNING):
        node = build_import_model([project_path])
    sub = node.get(DotPath('pkg.sub'))
    assert sub is not None
    assert sub.file_path == project_path / 'pkg' / 'sub' / '__init__.py'
    assert sub.imports == [ImportInModule(DotPath('package_import'), 1)]
    assert any(
        'sub.py' in record.message and record.levelno == logging.WARNING
        for record in caplog.records
    )


def test_syntax_error_is_skipped_with_warning(tmp_path: Path, caplog):
    """A file that fails to parse is skipped — it does not abort the model build."""
    (tmp_path / 'broken.py').write_text('1invalid_token = 2\n')
    (tmp_path / 'good.py').write_text('import x\n')
    with caplog.at_level(logging.WARNING):
        node = build_import_model([tmp_path])
    assert node.get(DotPath('good')).imports == [ImportInModule(DotPath('x'), 1)]
    assert node.get(DotPath('broken')) is None
    assert any(
        'broken.py' in record.message and record.levelno == logging.WARNING
        for record in caplog.records
    )


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'myapp': {
                '__init__.py': 'from . import a',
                'a.py': 'import os',
                'sub': {'__init__.py': '', 'b.py': 'from .. import a'},
            },
            'other.py': '',
        }
    ],
)
def test_package_as_source_root_is_named_from_its_import_root(project_path, caplog):
    with caplog.at_level(logging.WARNING):
        node = build_import_model([project_path / 'myapp'])
    assert [str(c.dot_path) for c in node.children()] == ['myapp']
    assert node.get(DotPath('myapp')).imports == [
        ImportInModule(DotPath('myapp.a'), 1, level=1, is_from_import=True)
    ]
    assert node.get(DotPath('myapp.sub.b')).imports == [
        ImportInModule(DotPath('myapp.a'), 1, level=2, is_from_import=True)
    ]
    assert not caplog.records


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'myapp': {
                '__init__.py': '',
                'a.py': '',
                'sub': {'__init__.py': '', 'b.py': 'from .. import a'},
            }
        }
    ],
)
def test_subpackage_as_source_root_walks_only_that_subpackage(project_path):
    node = build_import_model([project_path / 'myapp' / 'sub'])
    assert node.get(DotPath('myapp.sub.b')).imports == [
        ImportInModule(DotPath('myapp.a'), 1, level=2, is_from_import=True)
    ]
    assert node.get(DotPath('myapp.a')) is None


@pytest.mark.parametrize(
    'project_structure',
    [{'myapp': {'__init__.py': '', 'a.py': 'import os'}}],
)
@pytest.mark.parametrize('nested', ['myapp', '.'])
def test_nested_source_root_is_skipped(project_path, nested, caplog):
    with caplog.at_level(logging.WARNING):
        node = build_import_model([project_path / nested, project_path])
    assert node.get(DotPath('myapp.a')).imports == [ImportInModule(DotPath('os'), 1)]
    assert len(caplog.records) == 1
    assert 'inside source root' in caplog.records[0].message


def _timings(project_path: Path, module: str = 'm') -> list[tuple[str, str]]:
    node = build_import_model([project_path]).get(DotPath(module))
    return [(str(i.dot_path), i.timing) for i in node.imports]


@pytest.mark.parametrize(
    ('project_structure', 'expected'),
    [
        pytest.param({'m.py': 'import a'}, [('a', 'top')], id='module level'),
        pytest.param(
            {
                'm.py': """
                    try:
                        import a
                    except ImportError:
                        import b
                """
            },
            [('a', 'top'), ('b', 'top')],
            id='try/except',
        ),
        pytest.param(
            {
                'm.py': """
                    class C:
                        import a
                """
            },
            [('a', 'top')],
            id='class body',
        ),
        pytest.param(
            {
                'm.py': """
                    if x:
                        import a
                    with y:
                        import b
                    match z:
                        case 1:
                            import c
                """
            },
            [('a', 'top'), ('b', 'top'), ('c', 'top')],
            id='if/with/match',
        ),
        pytest.param(
            {
                'm.py': """
                    if TYPE_CHECKING:
                        import a
                    if typing.TYPE_CHECKING:
                        import b
                    if t.TYPE_CHECKING:
                        import c
                """
            },
            [('a', 'type_checking'), ('b', 'type_checking'), ('c', 'type_checking')],
            id='TYPE_CHECKING name and attribute',
        ),
        pytest.param(
            {
                'm.py': """
                    if TYPE_CHECKING:
                        import a
                    else:
                        import b
                """
            },
            [('a', 'type_checking'), ('b', 'top')],
            id='TYPE_CHECKING else',
        ),
        pytest.param(
            {
                'm.py': """
                    if TYPE_CHECKING:
                        if TYPE_CHECKING:
                            import a
                        if x:
                            import b
                        else:
                            import c
                """
            },
            [('a', 'type_checking'), ('b', 'type_checking'), ('c', 'type_checking')],
            id='nested in TYPE_CHECKING',
        ),
        pytest.param(
            {
                'm.py': """
                    if TC:
                        import a
                    if not TYPE_CHECKING:
                        import b
                    if TYPE_CHECKING and x:
                        import c
                """
            },
            [('a', 'top'), ('b', 'top'), ('c', 'top')],
            id='unrecognized TYPE_CHECKING',
        ),
        pytest.param(
            {
                'm.py': """
                    def f():
                        import a
                    async def g():
                        import b
                    class C:
                        def method(self):
                            import c
                    def outer():
                        def inner():
                            try:
                                import d
                            except ImportError:
                                pass
                """
            },
            [
                ('a', 'function'),
                ('b', 'function'),
                ('c', 'function'),
                ('d', 'function'),
            ],
            id='function level',
        ),
        pytest.param(
            {
                'm.py': """
                    if TYPE_CHECKING:
                        def f():
                            import a
                    def g():
                        if TYPE_CHECKING:
                            import b
                """
            },
            [('a', 'function'), ('b', 'function')],
            id='function wins over TYPE_CHECKING',
        ),
    ],
)
def test_timing(project_path: Path, expected):
    assert _timings(project_path) == expected


@pytest.mark.parametrize(
    ('project_structure', 'expected'),
    [
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a', 'b']
                    import a
                    from b import x
                    import c
                """
            },
            [('a', 'lazy'), ('b.x', 'lazy'), ('c', 'top')],
            id='list',
        ),
        pytest.param(
            {'m.py': "__lazy_modules__ = ('a',)\nimport a"},
            [('a', 'lazy')],
            id='tuple',
        ),
        pytest.param(
            {'m.py': "__lazy_modules__ = {'a'}\nimport a"},
            [('a', 'lazy')],
            id='set',
        ),
        pytest.param(
            {'m.py': "__lazy_modules__: list[str] = ['a']\nimport a"},
            [('a', 'lazy')],
            id='annotated assignment',
        ),
        pytest.param(
            {'m.py': '__lazy_modules__: list[str]\nimport a'},
            [('a', 'top')],
            id='annotation without value',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a']
                    import a as b
                    from a import x as y
                """
            },
            [('a', 'lazy'), ('a.x', 'lazy')],
            id='aliased',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['pkg']
                    from pkg import sub
                    import pkg.sub
                """
            },
            [('pkg.sub', 'lazy'), ('pkg.sub', 'top')],
            id='statement module',
        ),
        pytest.param(
            {'m.py': "__lazy_modules__ = ['pkg.sub']\nimport pkg.sub, other"},
            [('pkg.sub', 'lazy'), ('other', 'top')],
            id='decided per alias',
        ),
        pytest.param(
            {'m.py': "__lazy_modules__ = ['a']\nfrom a import *"},
            [('a.*', 'top')],
            id='star import',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a', 'b', 'c', 'd', 'e']
                    if x:
                        import a
                    with y:
                        import b
                    match z:
                        case 1:
                            import c
                    for i in range(1):
                        import d
                    while False:
                        import e
                """
            },
            [('a', 'lazy'), ('b', 'lazy'), ('c', 'lazy'), ('d', 'lazy'), ('e', 'lazy')],
            id='module-level blocks',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a', 'b', 'c', 'd']
                    try:
                        import a
                    except ImportError:
                        import b
                    else:
                        import c
                    finally:
                        import d
                """
            },
            [('a', 'top'), ('b', 'top'), ('c', 'lazy'), ('d', 'lazy')],
            id='try',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a', 'b']
                    try:
                        import a
                    except* ImportError:
                        import b
                """
            },
            [('a', 'top'), ('b', 'top')],
            id='try/except*',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a']
                    class C:
                        import a
                """
            },
            [('a', 'top')],
            id='class body',
        ),
        pytest.param(
            {
                'm.py': """
                    import a
                    __lazy_modules__ = ['a']
                    import a
                """
            },
            [('a', 'top'), ('a', 'lazy')],
            id='before the assignment',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a']
                    import a
                    __lazy_modules__ = ['b']
                    import a
                    import b
                """
            },
            [('a', 'lazy'), ('a', 'top'), ('b', 'lazy')],
            id='reassignment replaces the set',
        ),
        pytest.param(
            {
                'm.py': """
                    __lazy_modules__ = ['a', 'b']
                    if TYPE_CHECKING:
                        import a
                    def f():
                        import b
                """
            },
            [('a', 'type_checking'), ('b', 'function')],
            id='TYPE_CHECKING and function win',
        ),
        pytest.param(
            {
                'm.py': """
                    if x:
                        __lazy_modules__ = ['a']
                    import a
                """
            },
            [('a', 'top')],
            id='nested assignment not followed',
        ),
    ],
)
def test_lazy_modules_timing(project_path: Path, expected, caplog):
    with caplog.at_level(logging.WARNING):
        assert _timings(project_path) == expected
    assert not caplog.records


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'rp': {
                '__init__.py': '',
                'm.py': """
                    __lazy_modules__ = ['rp.x']
                    from .x import v
                    from . import x
                """,
            }
        }
    ],
)
def test_lazy_modules_matches_resolved_relative_import(project_path: Path):
    assert _timings(project_path, 'rp.m') == [('rp.x.v', 'lazy'), ('rp.x', 'top')]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'm.py': """
                __lazy_modules__ = ['a']
                __lazy_modules__ = frozenset({'b'})
                __lazy_modules__ += ['b']
                __lazy_modules__ = 'b'
                __lazy_modules__ = ['b', 1]
                import a
                import b
            """
        }
    ],
)
def test_unrecognized_lazy_modules_assignment_is_ignored(project_path: Path, caplog):
    with caplog.at_level(logging.WARNING):
        assert _timings(project_path) == [('a', 'lazy'), ('b', 'top')]
    assert len(caplog.records) == 4
    for line_no, record in enumerate(caplog.records, start=2):
        assert 'Ignoring __lazy_modules__ assignment in ' in record.message
        assert f'line {line_no}:' in record.message


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'm.py': """
                def f():
                    import a
                import b
            """
        }
    ],
)
def test_imports_are_collected_in_source_order(project_path: Path):
    assert _timings(project_path) == [('a', 'function'), ('b', 'top')]


# Fails to parse on every interpreter, with or without lazy syntax support.
_LAZY_SOURCE_WITH_SYNTAX_ERROR = 'lazy import a\n1invalid_token = 2\n'


def test_lazy_syntax_on_old_python_warns(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.setattr('pytest_imports.parser._HAS_LAZY_SYNTAX', False)
    (tmp_path / 'm.py').write_text(_LAZY_SOURCE_WITH_SYNTAX_ERROR)
    with (
        caplog.at_level(logging.WARNING),
        pytest.warns(UserWarning, match=r'm\.py.*PEP 810.*Python 3\.15'),
    ):
        node = build_import_model([tmp_path])
    assert node.get(DotPath('m')) is None
    assert len(caplog.records) == 1


@pytest.mark.parametrize(
    ('has_lazy_syntax', 'source'),
    [
        (True, _LAZY_SOURCE_WITH_SYNTAX_ERROR),
        (False, '1invalid_token = 2\n'),
    ],
)
def test_syntax_error_without_lazy_hint_only_logs(
    tmp_path: Path, monkeypatch, caplog, has_lazy_syntax, source
):
    monkeypatch.setattr('pytest_imports.parser._HAS_LAZY_SYNTAX', has_lazy_syntax)
    (tmp_path / 'm.py').write_text(source)
    with caplog.at_level(logging.WARNING), warnings.catch_warnings():
        warnings.simplefilter('error')
        build_import_model([tmp_path])
    assert len(caplog.records) == 1


@pytest.mark.skipif(sys.version_info < (3, 15), reason='lazy syntax needs 3.15+')
@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'm.py': """
                lazy import a
                lazy from b import c
                if x:
                    lazy import d
                with y:
                    lazy import e
                if TYPE_CHECKING:
                    lazy import f
            """
        }
    ],
)
def test_lazy_keyword_timing(project_path: Path):
    assert _timings(project_path) == [
        ('a', 'lazy'),
        ('b.c', 'lazy'),
        ('d', 'lazy'),
        ('e', 'lazy'),
        ('f', 'type_checking'),
    ]
