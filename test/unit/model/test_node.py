from pathlib import Path

import pytest

from pytest_imports.model import DotPath, ImportInModule, ModuleNode, RootNode


@pytest.fixture
def tree_base_node():
    base_node = RootNode()
    base_node.get_or_add(DotPath('1'), Path('1'))
    base_node.get_or_add(DotPath('2'), Path('2'))
    base_node.get_or_add(DotPath('2.1'), Path('1', '2'))
    return base_node


@pytest.mark.parametrize(
    ('path_str', 'result_name'),
    [
        ('1', '1'),
        ('2', '2'),
        ('2.1', '1'),
    ],
)
def test_node_get(tree_base_node, path_str, result_name):
    assert tree_base_node.get(DotPath(path_str)).name == result_name


def test_node_get_nested(tree_base_node):
    assert tree_base_node.get(DotPath('2')).get(DotPath('1')).name == '1'


def test_node_get_non_existend(tree_base_node):
    assert tree_base_node.get(DotPath('1.1')) is None


def test_node_get_root(tree_base_node):
    with pytest.raises(KeyError):
        assert tree_base_node.get(DotPath())


def test_node_get_or_add():
    root_node = RootNode()
    new_node = root_node.get_or_add(DotPath('foo'), Path('bar'))
    assert new_node.name == 'foo'
    assert new_node.dot_path == DotPath('foo')
    assert new_node.file_path == Path('bar')
    assert root_node.get(DotPath('foo')).name == 'foo'


def test_node_dot_path_nested():
    root_node = RootNode()
    root_node.get_or_add(DotPath('a.b.c'), Path('a', 'b', 'c'))
    assert root_node.get(DotPath('a')).dot_path == DotPath('a')
    assert root_node.get(DotPath('a.b')).dot_path == DotPath('a.b')
    assert root_node.get(DotPath('a.b.c')).dot_path == DotPath('a.b.c')


def test_node_get_or_add_new_parent(tree_base_node):
    new_node = tree_base_node.get_or_add(DotPath('1.a.b'), Path('1', 'a', 'b'))
    assert new_node.name == 'b'
    assert new_node.file_path == Path('1', 'a', 'b')
    new_parent_node = tree_base_node.get(DotPath('1.a'))
    assert new_parent_node.name == 'a'
    assert new_parent_node.file_path == Path('1', 'a')
    assert new_parent_node.get(DotPath('b')).name == 'b'


def test_node_get_or_add_root(tree_base_node):
    with pytest.raises(KeyError):
        assert tree_base_node.get_or_add(DotPath(), Path())


def test_node_add_imports():
    imports = [
        ImportInModule(DotPath('a'), line_no=1),
        ImportInModule(DotPath('b'), line_no=2),
    ]
    node = ModuleNode('x', DotPath('y'), Path('z'))
    assert len(node.imports) == 0
    node.add_imports(imports)
    assert len(node.imports) == 2
    assert {str(import_of.dot_path) for import_of in node.imports} == {
        'a',
        'b',
    }


def test_node_for_init_file():
    imports = [
        ImportInModule(DotPath('a'), line_no=1),
        ImportInModule(DotPath('b'), line_no=2),
    ]
    node = ModuleNode('x', DotPath('x'), Path('foobar'))
    assert node.file_path.name == 'foobar'
    assert len(node.imports) == 0
    node.add_data_for_init_file(imports)
    assert len(node.imports) == 2
    assert node.file_path == Path('foobar') / '__init__.py'


def test_node_walk():
    base_node = ModuleNode('base', DotPath('base'), Path())
    base_node.get_or_add(DotPath('a.c'), Path())
    base_node.get_or_add(DotPath('a.b.x'), Path())
    visited = [node.name for node in base_node.walk()]
    assert len(visited) == 5
    assert set(visited) == {'base', 'a', 'c', 'b', 'x'}


@pytest.mark.parametrize(
    ('exclude', 'visited'),
    [
        ([], {'r', 'a', 'b', 'c', 'd'}),
        ([''], {'r', 'a', 'b', 'c', 'd'}),
        (['r'], {'r', 'a', 'b', 'c', 'd'}),
        (['b'], {'r', 'a', 'b', 'c', 'd'}),
        (['d'], {'r', 'a', 'b', 'c', 'd'}),
        (['x'], {'r', 'a', 'b', 'c', 'd'}),
        (['a'], {'r'}),
        (['a', 'a'], {'r'}),
        (['a.b'], {'r', 'a', 'd'}),
        (['a.b', 'a'], {'r'}),
        (['a.b', 'a.d'], {'r', 'a'}),
        (['a.b', 'a.d', 'x.y'], {'r', 'a'}),
    ],
)
def test_node_walk_exclude(exclude, visited):
    base_node = ModuleNode('r', DotPath('r'), Path())
    base_node.get_or_add(DotPath('a.b.c'), Path())
    base_node.get_or_add(DotPath('a.d'), Path())
    assert {
        node.name for node in base_node.walk(exclude=[DotPath(p) for p in exclude])
    } == visited
