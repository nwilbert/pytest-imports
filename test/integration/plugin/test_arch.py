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
