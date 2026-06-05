def test_explain_must_import_fail(pytester):
    pytester.makepyfile(foo='import fizz')
    pytester.makepyfile("""
        from pytest_imports import must_import

        def test_arch(imports):
            imports.check({'foo': must_import('bar')})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'no matching import' in line
    ]
    assert len(explanation_lines) == 1
    assert 'foo.py' in explanation_lines[0]


def test_explain_must_not_import_fail(pytester):
    pytester.makepyfile(
        foobar="""
        from foo import bar
        import foo.bar
    """
    )
    pytester.makepyfile("""
        from pytest_imports import must_not_import

        def test_arch(imports):
            imports.check({'foobar': must_not_import('foo.bar')})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'found in' in line
    ]
    assert len(explanation_lines) == 2
    assert 'foobar.py:1' in explanation_lines[0]
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
