from inspect import cleandoc


def test_project_path_from_toml_config(pytester):
    """Test that config values are read from pyproject.toml"""
    pytester.makepyprojecttoml("""
        [tool.pytest.ini_options]
        imports_project_paths = [
            "foobar",
            "/foo/bar"
        ]
    """)
    pytester.makepyfile("""
        from pathlib import Path

        def test_arch(imports_project_paths, pytestconfig):
            assert len(imports_project_paths) == 2
            assert imports_project_paths[0] == pytestconfig.rootpath / 'foobar'
            assert imports_project_paths[1] == Path('/foo/bar').absolute()
    """)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_project_path_from_ini_config(pytester):
    """Test that config values are read from tox.ini"""
    pytester.makeini("""
        [pytest]
        imports_project_paths =
            foobar
            /foo/bar
    """)
    pytester.makepyfile("""
        from pathlib import Path

        def test_arch(imports_project_paths, pytestconfig):
            assert len(imports_project_paths) == 2
            assert imports_project_paths[0] == pytestconfig.rootpath / 'foobar'
            assert imports_project_paths[1] == Path('/foo/bar').absolute()

    """)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_project_path_from_heuristic_with_src_dir(pytester):
    """Test that config values are read from tox.ini"""
    (pytester.path / 'root' / 'src' / 'foobar').mkdir(parents=True)
    (pytester.path / 'root' / 'test').mkdir(parents=True)
    (pytester.path / 'root' / 'pyproject.toml').write_text('#')
    expected = str(pytester.path / 'root' / 'src')
    (pytester.path / 'root' / 'test' / 'test_path.py').write_text(
        cleandoc(f"""
            def test_path(imports_project_paths):
                assert len(imports_project_paths) == 1
                assert str(imports_project_paths[0]) == {expected!r}
            """)
    )
    result = pytester.runpytest('--rootdir', pytester.path / 'root' / 'test')
    result.assert_outcomes(passed=1)


def test_project_path_from_heuristic_with_nested_dirs(pytester):
    """Test that config values are read from tox.ini"""
    (pytester.path / 'root' / 'foobar').mkdir(parents=True)
    (pytester.path / 'root' / 'test1' / 'test2').mkdir(parents=True)
    (pytester.path / 'root' / 'pyproject.toml').write_text('#')
    expected = str(pytester.path / 'root')
    (pytester.path / 'root' / 'test1' / 'test2' / 'test_path.py').write_text(
        cleandoc(f"""
            def test_path(imports_project_paths):
                assert len(imports_project_paths) == 1
                assert str(imports_project_paths[0]) == {expected!r}
            """)
    )
    result = pytester.runpytest('--rootdir', pytester.path / 'root' / 'test1' / 'test2')
    result.assert_outcomes(passed=1)


def test_project_path_from_heuristic_with_setup_py(pytester):
    """Test that config values are read from tox.ini"""
    (pytester.path / 'root' / 'foobar').mkdir(parents=True)
    (pytester.path / 'root' / 'test').mkdir(parents=True)
    (pytester.path / 'root' / 'setup.py').write_text('#')
    expected = str(pytester.path / 'root')
    (pytester.path / 'root' / 'test' / 'test_path.py').write_text(
        cleandoc(f"""
            def test_path(imports_project_paths):
                assert len(imports_project_paths) == 1
                assert str(imports_project_paths[0]) == {expected!r}
            """)
    )
    result = pytester.runpytest('--rootdir', pytester.path / 'root' / 'test')
    result.assert_outcomes(passed=1)


def test_multiple_project_paths(pytester):
    (pytester.path / 'root1' / 'foo').mkdir(parents=True)
    (pytester.path / 'root1' / 'foo' / '__init__.py').write_text('')
    (pytester.path / 'root1' / 'foo' / 'a.py').write_text('from bar import b')
    (pytester.path / 'root2' / 'bar').mkdir(parents=True)
    (pytester.path / 'root2' / 'bar' / '__init__.py').write_text('')
    (pytester.path / 'root2' / 'bar' / 'b.py').write_text('x = 1')
    pytester.makepyprojecttoml("""
        [tool.pytest.ini_options]
        imports_project_paths = [
            "root1",
            "root2",
        ]
    """)
    pytester.makepyfile("""
        from pytest_imports import must_import, must_not_import, scope

        def test_arch(imports):
            imports.check({
                scope('foo.a'): must_import('bar.b'),
                scope('bar.b'): must_not_import('foo'),
            })
    """)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
