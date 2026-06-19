import pytest

from pytest_imports.model import DotPath, RootNode
from pytest_imports.query import (
    Descendants,
    Internal,
    _find_matching_imports,
    _find_matching_private_imports,
    _format_target,
    _match_target,
    descendants,
    internal,
    must_import,
    must_not_import,
    must_not_import_private,
    must_only_import,
    project,
    scope,
)


def test_scope_hashable():
    s = scope('foo.bar')
    assert {s: 'value'}[s] == 'value'


def test_scope_without():
    s = scope('foo', without=['bar', 'baz'])
    assert s.without == ('bar', 'baz')


def test_scope_without_single_string():
    s = scope('foo', without='bar')
    assert s.without == ('bar',)


def test_project():
    p = project()
    assert p.path is None
    assert p.without == ()


def test_project_hashable():
    p = project()
    assert {p: 'value'}[p] == 'value'


def test_must_import_defaults():
    p = must_import('foo.bar')
    assert p.path == ('foo.bar',)
    assert p.via is None


def test_must_import_list_of_targets():
    p = must_import(['a', 'b'])
    assert p.path == ('a', 'b')


def test_must_import_via():
    assert must_import('foo', via='absolute').via == 'absolute'
    assert must_import('foo', via='relative').via == 'relative'


def test_must_not_import_defaults():
    p = must_not_import('foo.bar')
    assert p.path == ('foo.bar',)
    assert p.via is None


def test_must_not_import_list_of_targets():
    p = must_not_import([descendants('a'), 'b'])
    assert p.path == (Descendants(path='a'), 'b')


def test_must_not_import_private_defaults():
    p = must_not_import_private()
    assert p.path == ()


def test_must_not_import_private_with_path():
    p = must_not_import_private('foo')
    assert p.path == ('foo',)


def test_must_not_import_private_accepts_structured_target():
    p = must_not_import_private(internal())
    assert p.path == (Internal(),)


def test_must_not_import_private_list_of_targets():
    p = must_not_import_private(['a', descendants('b')])
    assert p.path == ('a', Descendants(path='b'))


def test_must_only_import_single_target_normalized():
    p = must_only_import('foo.core')
    assert p.allowed == ('foo.core',)
    assert p.among == Internal()
    assert p.via is None


def test_must_only_import_list_of_targets():
    p = must_only_import(['foo.core', 'foo.schemas'])
    assert p.allowed == ('foo.core', 'foo.schemas')


def test_must_only_import_accepts_structured_targets():
    p = must_only_import(descendants('foo.core'))
    assert p.allowed == (Descendants(path='foo.core'),)


def test_must_only_import_among_and_via():
    p = must_only_import('foo.core', among=descendants('foo'), via='relative')
    assert p.among == Descendants(path='foo')
    assert p.via == 'relative'


def test_descendants_factory():
    d = descendants('foo.bar')
    assert d == Descendants(path='foo.bar')
    assert d.path == 'foo.bar'


def test_descendants_without_single_string():
    d = descendants('foo.bar', without='baz')
    assert d.without == ('baz',)


def test_descendants_without_list():
    d = descendants('foo', without=['a', 'b'])
    assert d.without == ('a', 'b')


def test_descendants_without_defaults_empty():
    assert descendants('foo').without == ()


def test_internal_factory():
    assert internal() == Internal()


def test_must_import_accepts_descendants():
    p = must_import(descendants('foo'))
    assert p.path == (Descendants(path='foo'),)


def test_must_not_import_accepts_internal():
    p = must_not_import(internal(), via='absolute')
    assert p.path == (Internal(),)
    assert p.via == 'absolute'


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_find_matching_imports_flat(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    assert list(_find_matching_imports(a, [], 'b', None, imports_root_node))
    assert list(_find_matching_imports(a, [], 'b.x', None, imports_root_node))
    assert not list(_find_matching_imports(a, [], 'c', None, imports_root_node))
    assert not list(_find_matching_imports(a, [], 'b.y', None, imports_root_node))
    assert not list(_find_matching_imports(a, [], 'b.x.y', None, imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'d': {'e.py': 'import x'}}],
)
def test_find_matching_imports_nested(imports_root_node):
    d = imports_root_node.get(DotPath('d'))
    assert list(_find_matching_imports(d, [], 'x', None, imports_root_node))
    assert not list(_find_matching_imports(d, [], 'y', None, imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import x\nimport x.y'}],
)
def test_find_matching_imports_returns_line_numbers(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    matches = list(_find_matching_imports(a, [], 'x', None, imports_root_node))
    assert len(matches) == 2
    assert matches[0][1].line_no == 1
    assert matches[1][1].line_no == 2


@pytest.mark.parametrize(
    ('project_structure', 'via', 'n_matches'),
    [
        ({'a.py': 'import x'}, 'absolute', 1),
        ({'a.py': 'from . import x'}, 'absolute', 0),
        ({'a.py': 'import x'}, 'relative', 0),
        ({'a.py': 'from . import x'}, 'relative', 1),
        ({'a.py': 'import x'}, None, 1),
        ({'a.py': 'from . import x'}, None, 1),
    ],
)
def test_find_matching_imports_via(imports_root_node, via, n_matches):
    a = imports_root_node.get(DotPath('a'))
    matches = list(_find_matching_imports(a, [], 'x', via, imports_root_node))
    assert len(matches) == n_matches


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x', 'b.py': 'import x'}}],
)
def test_find_matching_imports_exclude(imports_root_node):
    r = imports_root_node.get(DotPath('r'))
    matches = list(
        _find_matching_imports(r, [DotPath('b')], 'x', None, imports_root_node)
    )
    assert len(matches) == 1
    assert 'a.py' in str(matches[0][0].file_path)


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x', 'b.py': 'import x'}}],
)
def test_find_matching_imports_multiple_exclude(imports_root_node):
    r = imports_root_node.get(DotPath('r'))
    matches = list(
        _find_matching_imports(
            r, [DotPath('a'), DotPath('b')], 'x', None, imports_root_node
        )
    )
    assert len(matches) == 0


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import foo\nimport foo.bar'}],
)
def test_find_matching_imports_descendants_excludes_target(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    matches = list(
        _find_matching_imports(a, [], descendants('foo'), None, imports_root_node)
    )
    assert len(matches) == 1
    assert matches[0][1].dot_path == DotPath('foo.bar')


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import foo'}],
)
def test_find_matching_imports_descendants_does_not_match_target_alone(
    imports_root_node,
):
    a = imports_root_node.get(DotPath('a'))
    assert not list(
        _find_matching_imports(a, [], descendants('foo'), None, imports_root_node)
    )


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import b\nimport external', 'b.py': ''}],
)
def test_find_matching_imports_internal_matches_internal_only(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    matches = list(_find_matching_imports(a, [], internal(), None, imports_root_node))
    assert len(matches) == 1
    assert matches[0][1].dot_path == DotPath('b')


@pytest.mark.parametrize(
    'project_structure',
    [{'pkg': {'a.py': 'from . import b', 'b.py': ''}}],
)
def test_find_matching_imports_internal_matches_relative(imports_root_node):
    pkg = imports_root_node.get(DotPath('pkg'))
    matches = list(_find_matching_imports(pkg, [], internal(), None, imports_root_node))
    assert len(matches) == 1
    assert matches[0][1].dot_path == DotPath('pkg.b')


@pytest.mark.parametrize(
    'project_structure',
    [{'pkg': {'a.py': 'from pkg import b', 'b.py': ''}}],
)
def test_find_matching_imports_internal_absolute_via(imports_root_node):
    pkg = imports_root_node.get(DotPath('pkg'))
    assert list(
        _find_matching_imports(pkg, [], internal(), 'absolute', imports_root_node)
    )
    assert not list(
        _find_matching_imports(pkg, [], internal(), 'relative', imports_root_node)
    )


def test_match_target_string():
    root = RootNode()
    assert _match_target('foo', DotPath('foo'), root)
    assert _match_target('foo', DotPath('foo.bar'), root)
    assert not _match_target('foo', DotPath('bar'), root)


def test_match_target_descendants():
    root = RootNode()
    assert not _match_target(descendants('foo'), DotPath('foo'), root)
    assert _match_target(descendants('foo'), DotPath('foo.bar'), root)
    assert not _match_target(descendants('foo'), DotPath('bar'), root)


def test_match_target_descendants_without_single():
    root = RootNode()
    d = descendants('a', without='b')
    assert _match_target(d, DotPath('a.c'), root)
    assert not _match_target(d, DotPath('a.b'), root)
    assert not _match_target(d, DotPath('a.b.c'), root)


def test_match_target_descendants_without_list():
    root = RootNode()
    d = descendants('a', without=['b', 'd'])
    assert _match_target(d, DotPath('a.c'), root)
    assert not _match_target(d, DotPath('a.b'), root)
    assert not _match_target(d, DotPath('a.d'), root)


def test_match_target_descendants_without_nested_path():
    root = RootNode()
    d = descendants('a', without='b.x')
    assert _match_target(d, DotPath('a.b.y'), root)
    assert not _match_target(d, DotPath('a.b.x'), root)
    assert not _match_target(d, DotPath('a.b.x.z'), root)


def test_format_target_descendants_without():
    assert _format_target(descendants('a', without='b')) == (
        'descendants of a except {b}'
    )
    assert _format_target(descendants('a', without=['b', 'c'])) == (
        'descendants of a except {b, c}'
    )
    assert _format_target(descendants('a')) == 'descendants of a'


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': '', 'b.py': ''}],
)
def test_match_target_internal(imports_root_node):
    assert _match_target(internal(), DotPath('a'), imports_root_node)
    assert _match_target(internal(), DotPath('b'), imports_root_node)
    assert not _match_target(internal(), DotPath('external'), imports_root_node)


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import _x'}],
)
def test_find_matching_private_imports_matches_private(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    assert list(_find_matching_private_imports(a, [], (), imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_find_matching_private_imports_ignores_public(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    assert not list(_find_matching_private_imports(a, [], (), imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from __future__ import annotations'}],
)
def test_find_matching_private_imports_ignores_future(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    assert not list(_find_matching_private_imports(a, [], (), imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import _x\nfrom c import _y'}],
)
def test_find_matching_private_imports_path_filter(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    assert (
        len(list(_find_matching_private_imports(a, [], ('b',), imports_root_node))) == 1
    )
    assert (
        len(list(_find_matching_private_imports(a, [], ('c',), imports_root_node))) == 1
    )
    assert len(list(_find_matching_private_imports(a, [], (), imports_root_node))) == 2


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'from b import _x', 'c.py': 'from d import y'}}],
)
def test_find_matching_private_imports_nested(imports_root_node):
    r = imports_root_node.get(DotPath('r'))
    matches = list(_find_matching_private_imports(r, [], (), imports_root_node))
    assert len(matches) == 1
    assert 'a.py' in str(matches[0][0].file_path)
