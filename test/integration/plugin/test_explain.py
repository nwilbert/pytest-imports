def test_explain_must_import_fail(pytester):
    pytester.makepyfile(foo='import fizz')
    pytester.makepyfile("""
        from pytest_imports import must_import, scope

        def test_arch(imports):
            imports.check({scope('foo'): must_import('bar')})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'no matching import' in line
    ]
    assert len(explanation_lines) == 1
    assert 'must import bar' in explanation_lines[0]
    assert 'scope foo' in explanation_lines[0]


def test_explain_must_not_import_fail(pytester):
    pytester.makepyfile(
        foobar="""
        from foo import bar
        import foo.bar
    """
    )
    pytester.makepyfile("""
        from pytest_imports import must_not_import, scope

        def test_arch(imports):
            imports.check({scope('foobar'): must_not_import('foo.bar')})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must not import' in line
    ]
    assert len(explanation_lines) == 2
    assert 'foobar.py:1' in explanation_lines[0]
    assert 'foobar.py:2' in explanation_lines[1]
    # The single-target message now names the matched import too.
    assert 'must not import foo.bar — found foo.bar in' in explanation_lines[0]


def test_explain_must_not_import_list_fail(pytester):
    pytester.makepyfile(
        foobar="""
        import foo
        import bar
        import keep
    """
    )
    pytester.makepyfile("""
        from pytest_imports import must_not_import, scope

        def test_arch(imports):
            imports.check({scope('foobar'): must_not_import(['foo', 'bar'])})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must not import' in line
    ]
    assert len(explanation_lines) == 2
    assert all('{foo, bar}' in line for line in explanation_lines)
    assert 'found foo matching foo' in explanation_lines[0]
    assert 'foobar.py:1' in explanation_lines[0]
    assert 'found bar matching bar' in explanation_lines[1]
    assert 'foobar.py:2' in explanation_lines[1]


def test_explain_must_not_import_descendants_fail(pytester):
    (pytester.path / 'myapp').mkdir()
    (pytester.path / 'myapp' / '__init__.py').write_text('')
    (pytester.path / 'myapp' / 'capture').mkdir()
    (pytester.path / 'myapp' / 'capture' / '__init__.py').write_text('')
    (pytester.path / 'myapp' / 'capture' / 'parser.py').write_text('x = 1')
    (pytester.path / 'myapp' / 'other.py').write_text(
        'from myapp.capture.parser import x'
    )
    pytester.makepyfile("""
        from pytest_imports import descendants, must_not_import, scope

        def test_arch(imports):
            imports.check({
                scope('myapp', without='capture'):
                    must_not_import(descendants('myapp.capture')),
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must not import' in line
    ]
    assert len(explanation_lines) == 1
    assert 'descendants of myapp.capture' in explanation_lines[0]
    assert 'myapp.capture.parser' in explanation_lines[0]
    assert 'other.py:1' in explanation_lines[0]


def test_explain_must_not_import_descendants_without_fail(pytester):
    (pytester.path / 'myapp').mkdir()
    (pytester.path / 'myapp' / '__init__.py').write_text('')
    (pytester.path / 'myapp' / 'contrib').mkdir()
    (pytester.path / 'myapp' / 'contrib' / '__init__.py').write_text('')
    (pytester.path / 'myapp' / 'contrib' / 'admin.py').write_text('x = 1')
    (pytester.path / 'myapp' / 'contrib' / 'gis.py').write_text('x = 1')
    (pytester.path / 'myapp' / 'core.py').write_text(
        'from myapp.contrib.admin import x\nfrom myapp.contrib.gis import x\n'
    )
    pytester.makepyfile("""
        from pytest_imports import descendants, must_not_import, scope

        def test_arch(imports):
            imports.check({
                scope('myapp.core'):
                    must_not_import(descendants('myapp.contrib', without='admin')),
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must not import' in line
    ]
    # admin is carved out; only the gis import is flagged.
    assert len(explanation_lines) == 1
    assert 'descendants of myapp.contrib except {admin}' in explanation_lines[0]
    assert 'myapp.contrib.gis' in explanation_lines[0]


def test_explain_must_not_import_private_internal_fail(pytester):
    (pytester.path / 'myapp').mkdir()
    (pytester.path / 'myapp' / '__init__.py').write_text('')
    (pytester.path / 'myapp' / '_secret.py').write_text('x = 1')
    (pytester.path / 'myapp' / 'a.py').write_text('from myapp._secret import x')
    (pytester.path / 'caller.py').write_text('from external._priv import y')
    pytester.makepyfile("""
        from pytest_imports import internal, must_not_import_private, project

        def test_arch(imports):
            imports.check({
                project(): must_not_import_private(internal()),
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must not import private' in line
    ]
    # The internal private import is flagged; the external one is not.
    assert len(explanation_lines) == 1
    assert 'from any internal module' in explanation_lines[0]
    assert 'a.py:1' in explanation_lines[0]


def test_explain_must_only_import_fail(pytester):
    (pytester.path / 'myapp').mkdir()
    (pytester.path / 'myapp' / '__init__.py').write_text('')
    for layer in ('core', 'schemas', 'persistence'):
        (pytester.path / 'myapp' / layer).mkdir()
        (pytester.path / 'myapp' / layer / '__init__.py').write_text('')
    (pytester.path / 'myapp' / 'api').mkdir()
    (pytester.path / 'myapp' / 'api' / '__init__.py').write_text('')
    (pytester.path / 'myapp' / 'api' / 'routes.py').write_text(
        'from myapp.core import service\nfrom myapp.persistence import db\nimport os\n'
    )
    pytester.makepyfile("""
        from pytest_imports import must_only_import, scope

        def test_arch(imports):
            imports.check({
                scope('myapp.api'):
                    must_only_import(['myapp.core', 'myapp.schemas']),
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must only import' in line
    ]
    # myapp.core is allowed and os is external (outside `among`); only the
    # persistence import is flagged.
    assert len(explanation_lines) == 1
    assert '{myapp.core, myapp.schemas}' in explanation_lines[0]
    assert 'among any internal module' in explanation_lines[0]
    assert 'myapp.persistence.db' in explanation_lines[0]
    assert 'routes.py:2' in explanation_lines[0]


def test_explain_must_not_import_internal_fail(pytester):
    (pytester.path / 'pkg').mkdir()
    (pytester.path / 'pkg' / '__init__.py').write_text('')
    (pytester.path / 'pkg' / 'a.py').write_text('from pkg.b import x')
    (pytester.path / 'pkg' / 'b.py').write_text('x = 1')
    pytester.makepyfile("""
        from pytest_imports import internal, must_not_import, project

        def test_arch(imports):
            imports.check({
                project(): must_not_import(internal(), via='absolute'),
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must not import' in line
    ]
    assert len(explanation_lines) == 1
    assert 'any internal module' in explanation_lines[0]
    assert 'pkg.b' in explanation_lines[0]
    assert 'a.py:1' in explanation_lines[0]
