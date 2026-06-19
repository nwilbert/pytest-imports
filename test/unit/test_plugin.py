import pytest

from pytest_imports import (
    descendants,
    internal,
    must_import,
    must_not_import,
    must_not_import_private,
    must_only_import,
    project,
    scope,
)


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_must_import_passes(imports):
    imports.check({scope('a'): must_import('b.x')})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_must_import_fails(imports):
    with pytest.raises(AssertionError, match='must import'):
        imports.check({scope('a'): must_import('c')})


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': '', 'b.py': '', 'c.py': ''}}],
)
def test_check_must_import_emits_one_message_per_failing_rule(imports):
    """A failing must_import rule on a scope of N files reports once, not N times.

    The rule is satisfied if any descendant in scope imports the target,
    so a failure is a single scope-level fact.
    """
    failures = imports.violations({scope('r'): must_import('x')})
    assert len(failures) == 1
    assert 'must import x' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x'}}],
)
def test_check_must_import_list_and_semantics(imports):
    # Conjunctive: x is present, y is missing → one failure for y only.
    imports.check({scope('r'): must_import(['x'])})
    failures = imports.violations({scope('r'): must_import(['x', 'y'])})
    assert len(failures) == 1
    assert 'must import y' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [{'m.py': 'import a\nimport a.sub\nimport b\nimport c'}],
)
def test_check_must_not_import_list_or_semantics(imports):
    # Disjunctive: a, a.sub, and b are flagged; c is ignored.
    failures = imports.violations({scope('m'): must_not_import(['a', 'b'])})
    assert len(failures) == 3
    assert all('{a, b}' in f for f in failures)
    assert any('matching a' in f for f in failures)
    assert any('matching b' in f for f in failures)
    assert not any('matching' in f and ' c ' in f for f in failures)


@pytest.mark.parametrize(
    'project_structure',
    [{'m.py': 'import a\nimport a.sub\nimport b'}],
)
def test_check_must_not_import_mixed_target_shapes(imports):
    # descendants('a') matches a.sub (not a); 'b' matches b → 2 failures.
    failures = imports.violations(
        {scope('m'): must_not_import([descendants('a'), 'b'])}
    )
    assert len(failures) == 2
    actual = ' '.join(failures)
    assert 'a.sub' in actual
    assert 'found b' in actual


@pytest.mark.parametrize(
    'project_structure',
    [{'m.py': 'import a'}],
)
def test_check_must_not_import_empty_list_vacuous(imports):
    assert imports.violations({scope('m'): must_not_import([])}) == []


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_must_not_import_passes(imports):
    imports.check({scope('a'): must_not_import('c')})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_must_not_import_fails(imports):
    with pytest.raises(AssertionError, match='must not import'):
        imports.check({scope('a'): must_not_import('b')})


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x', 'b.py': 'import y'}}],
)
def test_check_scope_without(imports):
    imports.check({scope('r', without='b'): must_not_import('y')})
    with pytest.raises(AssertionError):
        imports.check({scope('r', without='b'): must_not_import('x')})


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'r': {
                'a.py': 'import a_imp',
                'b': {
                    'c.py': 'import c_imp',
                    'd.py': 'import d_imp',
                },
            }
        }
    ],
)
def test_check_scope_without_nested_path(imports):
    """`without=` accepts dotted nested paths, not just direct submodule names."""
    # `without='b.c'` excludes r.b.c only — r.a and r.b.d are still in scope.
    imports.check({scope('r', without='b.c'): must_not_import('c_imp')})
    with pytest.raises(AssertionError, match=r'a\.py'):
        imports.check({scope('r', without='b.c'): must_not_import('a_imp')})
    with pytest.raises(AssertionError, match=r'd\.py'):
        imports.check({scope('r', without='b.c'): must_not_import('d_imp')})


@pytest.mark.parametrize(
    'project_structure',
    [{'r': {'a.py': 'import x', 'b.py': 'import y'}}],
)
def test_check_collects_all_failures(imports):
    with pytest.raises(AssertionError) as exc_info:
        imports.check({scope('r'): [must_not_import('x'), must_not_import('y')]})
    msg = str(exc_info.value)
    assert 'a.py' in msg
    assert 'b.py' in msg


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_list_of_predicates(imports):
    imports.check({scope('a'): [must_import('b'), must_not_import('c')]})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': ''}],
)
def test_check_module_not_found(imports):
    with pytest.raises(AssertionError, match='unknown scope'):
        imports.check({scope('foobar'): must_not_import('x')})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': ''}],
)
def test_check_empty_string_scope_reported_as_unknown(imports):
    with pytest.raises(AssertionError, match='unknown scope'):
        imports.check({scope(''): must_not_import('x')})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_unknown_scope_does_not_abort_remaining_rules(imports):
    """An unknown scope is reported as a failure but other rules still run."""
    failures = imports.violations(
        {
            scope('does_not_exist'): must_not_import('b'),
            scope('a'): must_not_import('b'),
        }
    )
    assert len(failures) == 2
    assert any('unknown scope' in f and 'does_not_exist' in f for f in failures)
    assert any('must not import b' in f for f in failures)


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'a': {
                'b.py': 'from .x import y',
                'd.py': 'from x import y',
            }
        }
    ],
)
def test_check_via(imports):
    imports.check({scope('a.b'): must_not_import('a.x', via='absolute')})
    imports.check({scope('a.d'): must_not_import('x', via='relative')})
    with pytest.raises(AssertionError):
        imports.check({scope('a.b'): must_not_import('a.x', via='relative')})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_check_must_not_import_private_passes(imports):
    imports.check({scope('a'): must_not_import_private()})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import _x'}],
)
def test_check_must_not_import_private_fails(imports):
    with pytest.raises(AssertionError, match='must not import private'):
        imports.check({scope('a'): must_not_import_private()})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import _x\nfrom c import _y'}],
)
def test_check_must_not_import_private_with_path(imports):
    imports.check({scope('a'): must_not_import_private('c2')})
    with pytest.raises(AssertionError):
        imports.check({scope('a'): must_not_import_private('b')})


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'myapp': {'__init__.py': '', 'a.py': 'from myapp._x import y'},
            'caller.py': 'from external._z import w',
        }
    ],
)
def test_check_must_not_import_private_internal_filter(imports):
    # internal() flags the private import of an internal name but ignores
    # the private import of an external one.
    failures = imports.violations({project(): must_not_import_private(internal())})
    assert len(failures) == 1
    assert 'a.py' in failures[0]
    assert 'from any internal module' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'myapp': {
                '__init__.py': '',
                'capture': {
                    '__init__.py': '',
                    'a.py': 'from myapp.capture._x import y',
                },
                'other.py': 'from myapp._secret import z',
            }
        }
    ],
)
def test_check_must_not_import_private_descendants_filter(imports):
    # Only private imports under myapp.capture are flagged; the private
    # import of myapp._secret elsewhere is outside the filter.
    failures = imports.violations(
        {project(): must_not_import_private(descendants('myapp.capture'))}
    )
    assert len(failures) == 1
    assert 'a.py' in failures[0]
    assert 'descendants of myapp.capture' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import _x\nfrom c import _y\nfrom d import _z'}],
)
def test_check_must_not_import_private_list_filter(imports):
    failures = imports.violations({scope('a'): must_not_import_private(['b', 'c'])})
    assert len(failures) == 2
    assert all('from {b, c}' in f for f in failures)


def _layered(routes_source: str) -> dict:
    """A small layered app: api/routes.py plus core/schemas/persistence."""
    return {
        'myapp': {
            'api': {'routes.py': routes_source},
            'core': {'__init__.py': '', 'detail.py': ''},
            'schemas': {'__init__.py': ''},
            'persistence': {'__init__.py': ''},
            'other': {'__init__.py': ''},
        }
    }


@pytest.mark.parametrize(
    'project_structure',
    [
        _layered(
            'from myapp.core import service\nfrom myapp.schemas import User\nimport os'
        )
    ],
)
def test_check_must_only_import_passes(imports):
    imports.check(
        {scope('myapp.api'): must_only_import(['myapp.core', 'myapp.schemas'])}
    )


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.core.detail import X')],
)
def test_check_must_only_import_allows_descendant_of_allowed(imports):
    imports.check({scope('myapp.api'): must_only_import('myapp.core')})


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.persistence import db')],
)
def test_check_must_only_import_flags_disallowed_internal(imports):
    failures = imports.violations(
        {scope('myapp.api'): must_only_import(['myapp.core', 'myapp.schemas'])}
    )
    assert len(failures) == 1
    assert 'must only import' in failures[0]
    assert 'among any internal module' in failures[0]
    assert 'myapp.persistence.db' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [_layered('import os\nfrom fastapi import APIRouter')],
)
def test_check_must_only_import_ignores_external(imports):
    imports.check({scope('myapp.api'): must_only_import('myapp.core')})


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from . import helpers')],
)
def test_check_must_only_import_resolves_relative(imports):
    # `from . import helpers` in myapp.api.routes resolves to
    # myapp.api.helpers — internal but not allowed → violation.
    failures = imports.violations({scope('myapp.api'): must_only_import('myapp.core')})
    assert len(failures) == 1
    assert 'myapp.api.helpers' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [_layered('import myapp.core\nfrom myapp.core.detail import X')],
)
def test_check_must_only_import_descendants_in_allowed(imports):
    # descendants('myapp.core') permits myapp.core.detail but flags a
    # bare import of myapp.core itself.
    failures = imports.violations(
        {scope('myapp.api'): must_only_import(descendants('myapp.core'))}
    )
    assert len(failures) == 1
    assert 'myapp.core' in failures[0]
    assert 'descendants of myapp.core' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.persistence import db\nimport myapp.other')],
)
def test_check_must_only_import_one_failure_per_line(imports):
    failures = imports.violations({scope('myapp.api'): must_only_import('myapp.core')})
    assert len(failures) == 2


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.core import x\nfrom myapp.schemas.user import U')],
)
def test_check_must_only_import_mixed_target_types(imports):
    imports.check(
        {
            scope('myapp.api'): must_only_import(
                ['myapp.core', descendants('myapp.schemas')]
            )
        }
    )


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.persistence import db')],
)
def test_check_must_only_import_via_relative_ignores_absolute(imports):
    # Only relative imports are in the universe; the absolute import of
    # persistence is outside `via='relative'` → no violation.
    imports.check({scope('myapp.api'): must_only_import('myapp.core', via='relative')})


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.core import service\nimport os')],
)
def test_check_must_only_import_empty_allowlist(imports):
    failures = imports.violations({scope('myapp.api'): must_only_import([])})
    assert len(failures) == 1
    assert 'must not import anything among any internal module' in failures[0]
    assert 'myapp.core.service' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [_layered('from myapp.persistence import db')],
)
def test_check_must_only_import_vacuous_internal(imports):
    imports.check({scope('myapp.api'): must_only_import(internal())})


@pytest.mark.parametrize(
    'project_structure',
    [
        {
            'myapp': {
                'capture': {
                    'a.py': (
                        'from myapp.capture.helper import x\n'
                        'import os\n'
                        'from myapp.persistence import db'
                    ),
                    'helper.py': '',
                },
                'persistence': {'__init__.py': ''},
            }
        }
    ],
)
def test_check_must_only_import_among_descendants(imports):
    # among=descendants('myapp') bounds the universe to myapp.* imports.
    # Within it only myapp.capture.* is allowed: the capture-internal
    # import passes, `os` is outside `among` (ignored), and
    # myapp.persistence is in-universe but disallowed → one violation.
    failures = imports.violations(
        {
            scope('myapp.capture'): must_only_import(
                descendants('myapp.capture'), among=descendants('myapp')
            )
        }
    )
    assert len(failures) == 1
    assert 'myapp.persistence.db' in failures[0]
    assert 'descendants of myapp' in failures[0]


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import _x', 'c.py': 'from e import y'}],
)
def test_check_project_scope(imports):
    imports.check({project(): must_not_import('d')})
    with pytest.raises(AssertionError):
        imports.check({project(): must_not_import_private()})


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_violations_empty_when_rules_pass(imports):
    assert imports.violations({scope('a'): must_import('b')}) == []


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x', 'c.py': 'from b import y'}],
)
def test_violations_returns_failure_list_without_raising(imports):
    failures = imports.violations(
        {
            scope('a'): must_not_import('b'),
            scope('c'): must_not_import('b'),
        }
    )
    assert len(failures) == 2
    assert all('must not import b' in f for f in failures)


@pytest.mark.parametrize(
    'project_structure',
    [{'a.py': 'from b import x'}],
)
def test_violations_matches_check_assertion_content(imports):
    rules = {scope('a'): must_not_import('b')}
    failures = imports.violations(rules)
    with pytest.raises(AssertionError) as exc_info:
        imports.check(rules)
    for failure in failures:
        assert failure in str(exc_info.value)
