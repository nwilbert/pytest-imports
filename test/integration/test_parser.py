import logging
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
            {
                'a': {'b.py': 'from .. import y'},
            },
            'a.b',
            ImportInModule(dot_path=DotPath('y'), line_no=1, level=2),
        ),
        (
            {'a': {'b': {'c.py': '...\nfrom .. import y'}}},
            'a.b.c',
            ImportInModule(dot_path=DotPath('a.y'), line_no=2, level=2),
        ),
        (
            {'a': {'b.py': '...\n\nfrom .x import y'}},
            'a.b',
            ImportInModule(dot_path=DotPath('a.x.y'), line_no=3, level=1),
        ),
    ],
)
def test_relative_import(project_path: Path, path: DotPath, import_obj):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath(path)).imports == [import_obj]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a': {'b.py': 'from ... import y'},
        }
    ],
)
def test_relative_import_beyond_base(project_path, caplog):
    base_node = build_import_model([project_path])
    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert 'relative import' in warnings[0].msg
    assert base_node.get(DotPath('a.b')).imports == []


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
            {
                'a': {'b.py': 'import x'},
            },
            'a.b',
            ImportInModule(dot_path=DotPath('x'), line_no=1),
        ),
        (
            {'a': {'b': {'c.py': '...\nimport x as y'}}},
            'a.b.c',
            ImportInModule(dot_path=DotPath('x'), line_no=2),
        ),
    ],
)
def test_absolute_import(project_path: Path, path: DotPath, import_obj):
    base_node = build_import_model([project_path])
    assert base_node.get(DotPath(path)).imports == [import_obj]


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
