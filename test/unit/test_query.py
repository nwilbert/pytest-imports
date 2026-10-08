import sys

import pytest

from pytest_imports.model import DotPath, RootNode
from pytest_imports.query import (
    Descendants,
    Internal,
    MustAlias,
    Stdlib,
    ThirdParty,
    _as_timing_set,
    _find_alias_violations,
    _find_matching_imports,
    _find_matching_private_imports,
    _format_target,
    _match_target,
    _walk_imports,
    descendants,
    evaluate_rules,
    internal,
    must_alias,
    must_import,
    must_not_import,
    must_not_import_private,
    must_only_import,
    project,
    scope,
    stdlib,
    third_party,
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
    assert p.style is None


def test_must_import_list_of_targets():
    p = must_import(['a', 'b'])
    assert p.path == ('a', 'b')


def test_must_import_style():
    assert must_import('foo', style='absolute').style == 'absolute'
    assert must_import('foo', style='relative').style == 'relative'


def test_must_not_import_defaults():
    p = must_not_import('foo.bar')
    assert p.path == ('foo.bar',)
    assert p.style is None


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
    assert p.style is None


def test_must_only_import_list_of_targets():
    p = must_only_import(['foo.core', 'foo.schemas'])
    assert p.allowed == ('foo.core', 'foo.schemas')


def test_must_only_import_accepts_structured_targets():
    p = must_only_import(descendants('foo.core'))
    assert p.allowed == (Descendants(path='foo.core'),)


def test_must_only_import_among_and_style():
    p = must_only_import('foo.core', among=descendants('foo'), style='relative')
    assert p.among == Descendants(path='foo')
    assert p.style == 'relative'


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
    p = must_not_import(internal(), style='absolute')
    assert p.path == (Internal(),)
    assert p.style == 'absolute'


_TIMING_FACTORIES = [
    pytest.param(lambda **kw: must_import('a', **kw), id='must_import'),
    pytest.param(lambda **kw: must_not_import('a', **kw), id='must_not_import'),
    pytest.param(lambda **kw: must_not_import_private(**kw), id='private'),
    pytest.param(lambda **kw: must_only_import('a', **kw), id='must_only_import'),
]


@pytest.mark.parametrize('factory', _TIMING_FACTORIES)
def test_factory_timing_normalized_to_frozenset(factory):
    assert factory().timing is None
    assert factory(timing='top').timing == frozenset({'top'})
    assert factory(timing=['lazy', 'function']).timing == frozenset(
        {'lazy', 'function'}
    )


@pytest.mark.parametrize('factory', _TIMING_FACTORIES)
@pytest.mark.parametrize(
    'timing', [[], 'toplevel', ['top', 'eager'], True, ['top', ['lazy']], ('top',)]
)
def test_factory_rejects_invalid_timing(factory, timing):
    with pytest.raises(ValueError, match='timing must be one of'):
        factory(timing=timing)


# One third-party, private import per timing (besides the `typing` import).
_PRIVATE_IMPORT_PER_TIMING = """
    from typing import TYPE_CHECKING
    __lazy_modules__ = ['lazy_mod']
    from top_mod import _p
    from lazy_mod import _p
    if TYPE_CHECKING:
        from tc_mod import _p
    def f():
        from func_mod import _p
"""
_MODULE_BY_TIMING = {
    'top': 'top_mod',
    'lazy': 'lazy_mod',
    'type_checking': 'tc_mod',
    'function': 'func_mod',
}

_TIMING_FILTERS = [
    (None, {'top', 'lazy', 'function', 'type_checking'}),
    ('top', {'top'}),
    ('lazy', {'lazy'}),
    ('function', {'function'}),
    ('type_checking', {'type_checking'}),
    (['lazy', 'function'], {'lazy', 'function'}),
    (['top', 'lazy', 'type_checking'], {'top', 'lazy', 'type_checking'}),
]


@pytest.mark.parametrize('project_structure', [{'m.py': _PRIVATE_IMPORT_PER_TIMING}])
@pytest.mark.parametrize(('timing', 'expected'), _TIMING_FILTERS)
def test_walk_imports_timing_filter(imports_root_node, timing, expected):
    m = imports_root_node.get(DotPath('m'))
    walked = _walk_imports(m, [], timings=_as_timing_set(timing))
    assert {import_by.timing for _, import_by in walked} == expected


@pytest.mark.parametrize('project_structure', [{'m.py': _PRIVATE_IMPORT_PER_TIMING}])
def test_find_matching_private_imports_timing_filter(imports_root_node):
    m = imports_root_node.get(DotPath('m'))
    matches = list(
        _find_matching_private_imports(
            m, [], (), imports_root_node, timings=frozenset({'lazy', 'function'})
        )
    )
    assert [import_by.line_no for _, import_by in matches] == [4, 8]


@pytest.mark.parametrize('project_structure', [{'m.py': _PRIVATE_IMPORT_PER_TIMING}])
@pytest.mark.parametrize(('timing', 'expected'), _TIMING_FILTERS)
def test_must_import_timing_filter(imports_root_node, timing, expected):
    for import_timing, module in _MODULE_BY_TIMING.items():
        failures = evaluate_rules(
            imports_root_node, {scope('m'): must_import(module, timing=timing)}
        )
        assert (not failures) == (import_timing in expected)


@pytest.mark.parametrize('project_structure', [{'m.py': _PRIVATE_IMPORT_PER_TIMING}])
def test_must_only_import_timing_ignores_other_timings(imports_root_node):
    # Only the top-level import is checked; the others are not allowed but
    # fall outside the checked universe.
    rule = must_only_import('top_mod', among=third_party(), timing='top')
    assert evaluate_rules(imports_root_node, {scope('m'): rule}) == []


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_find_matching_imports_flat(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    assert list(_find_matching_imports(a, [], 'b', imports_root_node))
    assert list(_find_matching_imports(a, [], 'b.x', imports_root_node))
    assert not list(_find_matching_imports(a, [], 'c', imports_root_node))
    assert not list(_find_matching_imports(a, [], 'b.y', imports_root_node))
    assert not list(_find_matching_imports(a, [], 'b.x.y', imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'d': {'e.py': 'import x'}}],
)
def test_find_matching_imports_nested(imports_root_node):
    d = imports_root_node.get(DotPath('d'))
    assert list(_find_matching_imports(d, [], 'x', imports_root_node))
    assert not list(_find_matching_imports(d, [], 'y', imports_root_node))


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import x\nimport x.y'}],
)
def test_find_matching_imports_returns_line_numbers(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    matches = list(_find_matching_imports(a, [], 'x', imports_root_node))
    assert len(matches) == 2
    assert matches[0][1].line_no == 1
    assert matches[1][1].line_no == 2


@pytest.mark.parametrize(
    ('project_structure', 'style', 'n_matches'),
    [
        ({'p': {'a.py': 'import p.x'}}, 'absolute', 1),
        ({'p': {'a.py': 'from . import x'}}, 'absolute', 0),
        ({'p': {'a.py': 'import p.x'}}, 'relative', 0),
        ({'p': {'a.py': 'from . import x'}}, 'relative', 1),
        ({'p': {'a.py': 'import p.x'}}, None, 1),
        ({'p': {'a.py': 'from . import x'}}, None, 1),
    ],
)
def test_find_matching_imports_style(imports_root_node, style, n_matches):
    a = imports_root_node.get(DotPath('p.a'))
    matches = list(_find_matching_imports(a, [], 'p.x', imports_root_node, style=style))
    assert len(matches) == n_matches


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x', 'b.py': 'import x'}}],
)
def test_find_matching_imports_exclude(imports_root_node):
    r = imports_root_node.get(DotPath('r'))
    matches = list(_find_matching_imports(r, [DotPath('b')], 'x', imports_root_node))
    assert len(matches) == 1
    assert 'a.py' in str(matches[0][0].file_path)


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x', 'b.py': 'import x'}}],
)
def test_find_matching_imports_multiple_exclude(imports_root_node):
    r = imports_root_node.get(DotPath('r'))
    matches = list(
        _find_matching_imports(r, [DotPath('a'), DotPath('b')], 'x', imports_root_node)
    )
    assert len(matches) == 0


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import foo\nimport foo.bar'}],
)
def test_find_matching_imports_descendants_excludes_target(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    matches = list(_find_matching_imports(a, [], descendants('foo'), imports_root_node))
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
        _find_matching_imports(a, [], descendants('foo'), imports_root_node)
    )


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'import b\nimport external', 'b.py': ''}],
)
def test_find_matching_imports_internal_matches_internal_only(imports_root_node):
    a = imports_root_node.get(DotPath('a'))
    matches = list(_find_matching_imports(a, [], internal(), imports_root_node))
    assert len(matches) == 1
    assert matches[0][1].dot_path == DotPath('b')


@pytest.mark.parametrize(
    'project_structure',
    [{'pkg': {'a.py': 'from . import b', 'b.py': ''}}],
)
def test_find_matching_imports_internal_matches_relative(imports_root_node):
    pkg = imports_root_node.get(DotPath('pkg'))
    matches = list(_find_matching_imports(pkg, [], internal(), imports_root_node))
    assert len(matches) == 1
    assert matches[0][1].dot_path == DotPath('pkg.b')


@pytest.mark.parametrize(
    'project_structure',
    [{'pkg': {'a.py': 'from pkg import b', 'b.py': ''}}],
)
def test_find_matching_imports_internal_absolute_style(imports_root_node):
    pkg = imports_root_node.get(DotPath('pkg'))
    assert list(
        _find_matching_imports(pkg, [], internal(), imports_root_node, style='absolute')
    )
    assert not list(
        _find_matching_imports(pkg, [], internal(), imports_root_node, style='relative')
    )


def test_must_alias_factory():
    p = must_alias('numpy', 'np')
    assert p == MustAlias(path='numpy', alias='np')
    assert p.path == 'numpy'
    assert p.alias == 'np'


@pytest.mark.parametrize(
    ('project_structure', 'is_violation'),
    [
        ({'m.py': 'import numpy as np'}, False),
        ({'m.py': 'import numpy'}, True),
        ({'m.py': 'import numpy as foo'}, True),
        ({'m.py': 'import numpy.linalg'}, True),
        ({'m.py': 'import numpy.linalg as nl'}, False),
        ({'m.py': 'import numpy.linalg as np'}, True),
        ({'m.py': 'from numpy import array'}, False),
        ({'m.py': 'from numpy import linalg'}, False),
        ({'m.py': 'from numpy.linalg import inv'}, False),
        ({'m.py': 'from numpy import *'}, True),
        ({'m.py': 'from numpy.linalg import inv as solve'}, False),
        # Path does not match: the alias collides but the package does not.
        ({'m.py': 'import scipy as np'}, False),
    ],
)
def test_find_alias_violations_semantics(imports_root_node, is_violation):
    m = imports_root_node.get(DotPath('m'))
    violations = list(_find_alias_violations(m, [], 'numpy', 'np'))
    assert bool(violations) == is_violation


@pytest.mark.parametrize(
    'project_structure',
    [{'m.py': 'import numpy as np\nimport numpy'}],
)
def test_find_alias_violations_mixed_file_reports_only_violation(imports_root_node):
    m = imports_root_node.get(DotPath('m'))
    violations = list(_find_alias_violations(m, [], 'numpy', 'np'))
    assert len(violations) == 1
    assert violations[0][1].line_no == 2


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


def test_stdlib_factory():
    assert stdlib() == Stdlib()


def test_third_party_factory():
    assert third_party() == ThirdParty()


@pytest.mark.parametrize(
    ('dot_path', 'expected'),
    [
        ('os', stdlib()),
        ('os.path', stdlib()),
        ('_thread', stdlib()),
        ('__future__', stdlib()),
        ('requests', third_party()),
        ('tomli.loads', third_party()),
        ('tomllib', stdlib()),
        (
            'annotationlib',
            stdlib() if sys.version_info >= (3, 14) else third_party(),
        ),
    ],
)
def test_match_target_stdlib_or_third_party(dot_path, expected):
    matched = [
        t
        for t in (stdlib(), third_party())
        if _match_target(t, DotPath(dot_path), RootNode())
    ]
    assert matched == [expected]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'logging.py': '',
            'pkg': {
                '__init__.py': '',
                'a.py': """
                    from __future__ import annotations
                    import os.path
                    import _thread
                    import logging.handlers
                    import requests
                    from fastapi import FastAPI
                    import pkg
                    from . import b
                    from .json import y
                """,
                'b.py': '',
            },
        }
    ],
)
def test_internal_stdlib_third_party_partition_imports(imports_root_node):
    classes = (internal(), stdlib(), third_party())
    matched = {
        str(i.dot_path): [
            t for t in classes if _match_target(t, i.dot_path, imports_root_node)
        ]
        for i in imports_root_node.get(DotPath('pkg.a')).imports
    }
    assert matched == {
        '__future__.annotations': [stdlib()],
        'os.path': [stdlib()],
        '_thread': [stdlib()],
        # A project module shadowing a stdlib name is internal only.
        'logging.handlers': [internal()],
        'requests': [third_party()],
        'fastapi.FastAPI': [third_party()],
        'pkg': [internal()],
        'pkg.b': [internal()],
        # A relative import is internal even if the module does not exist.
        'pkg.json.y': [internal()],
    }


def test_format_target_stdlib_and_third_party():
    assert _format_target(stdlib()) == 'any stdlib module'
    assert _format_target(third_party()) == 'any third-party module'
