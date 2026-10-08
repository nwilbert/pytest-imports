from pytest_imports import (
    internal,
    must_import,
    must_not_import,
    must_not_import_private,
    must_only_import,
    project,
    scope,
    third_party,
)


def test_internal_dependencies(imports):
    # model is the leaf layer; parser and query each build on model only;
    # plugin wires everything together.
    imports.check(
        {
            scope('pytest_imports.model'): must_not_import(internal()),
            scope('pytest_imports.parser'): [
                must_import('pytest_imports.model'),
                must_only_import('pytest_imports.model'),
            ],
            scope('pytest_imports.query'): must_import('pytest_imports.model'),
            scope('pytest_imports.plugin'): must_import('pytest_imports.model'),
        }
    )


def test_only_plugin_wires_in_the_parser(imports):
    # The public API in __init__ re-exports query; only the plugin may
    # reach the parser (or the plugin module itself).
    imports.check(
        {
            scope('pytest_imports', without='plugin'): must_only_import(
                ['pytest_imports.model', 'pytest_imports.query']
            ),
        }
    )


def test_query_only_imports_model(imports):
    # query.py is the rule layer; among internal modules it may only
    # reach into model. Stated as an allowlist rather than enumerating
    # every other internal module as a denylist.
    imports.check(
        {
            scope('pytest_imports.query'): must_only_import('pytest_imports.model'),
        }
    )


def test_all_internal_imports_must_be_relative(imports):
    imports.check(
        {
            project(): must_not_import(internal(), style='absolute'),
        }
    )


def test_no_function_level_internal_imports(imports):
    # Cycles must be fixed by restructuring, not hidden in function bodies.
    imports.check(
        {
            project(): must_not_import(internal(), timing='function'),
        }
    )


def test_external_dependencies(imports):
    imports.check(
        {
            scope('pytest_imports', without='parser'): must_not_import('ast'),
            scope('pytest_imports', without='plugin'): must_not_import(third_party()),
            scope('pytest_imports'): must_only_import('pytest', among=third_party()),
        }
    )


def test_no_private_imports(imports):
    imports.check(
        {
            project(): must_not_import_private(),
        }
    )
