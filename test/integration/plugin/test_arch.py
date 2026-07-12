def test_simple_project(pytester):
    pytester.makepyfile(foobar='from foo import bar')
    pytester.makepyfile("""
        from pytest_imports import must_import, must_not_import, scope

        def test_arch(imports):
            imports.check({
                scope('foobar'): [must_import('foo.bar'), must_not_import('fiz')],
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_must_alias_passes_on_conventional_alias(pytester):
    pytester.makepyfile(
        analysis="""
        import numpy as np
        from numpy import array
        from numpy.linalg import inv
    """
    )
    pytester.makepyfile("""
        from pytest_imports import must_alias, scope

        def test_arch(imports):
            imports.check({scope('analysis'): must_alias('numpy', 'np')})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_must_alias_flags_wrong_alias(pytester):
    pytester.makepyfile(
        analysis="""
        import numpy as np
        import numpy
    """
    )
    pytester.makepyfile("""
        from pytest_imports import must_alias, scope

        def test_arch(imports):
            imports.check({scope('analysis'): must_alias('numpy', 'np')})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    explanation_lines = [
        line
        for line in result.outlines
        if line.lstrip().startswith('E') and 'must import numpy only as np' in line
    ]
    # Only the bare `import numpy` on line 2 is flagged.
    assert len(explanation_lines) == 1
    assert 'analysis.py:2' in explanation_lines[0]


def test_must_alias_is_scoped(pytester):
    (pytester.path / 'clean').mkdir()
    (pytester.path / 'clean' / '__init__.py').write_text('import numpy as np')
    (pytester.path / 'legacy').mkdir()
    (pytester.path / 'legacy' / '__init__.py').write_text('import numpy')
    pytester.makepyfile("""
        from pytest_imports import must_alias, scope

        def test_arch(imports):
            imports.check({scope('clean'): must_alias('numpy', 'np')})
    """)
    result = pytester.runpytest()
    # The violation lives in `legacy`, outside the scoped `clean` package.
    result.assert_outcomes(passed=1)
