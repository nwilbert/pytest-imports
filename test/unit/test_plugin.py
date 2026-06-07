import pytest

from pytest_imports import (
    must_import,
    must_not_import,
    must_not_import_private,
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
    with pytest.raises(KeyError):
        imports.check({scope('foobar'): must_not_import('x')})


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
