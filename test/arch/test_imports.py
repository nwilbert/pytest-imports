from pytest_imports import (
    internal,
    must_import,
    must_not_import,
    must_not_import_private,
    must_only_import,
    project,
    scope,
)


def test_internal_dependencies(imports):
    imports.check(
        {
            scope('pytest_imports.model'): [
                must_not_import('pytest_imports.parser'),
                must_not_import('pytest_imports.query'),
                must_not_import('pytest_imports.plugin'),
            ],
            scope('pytest_imports.parser'): [
                must_not_import('pytest_imports.query'),
                must_not_import('pytest_imports.plugin'),
            ],
            scope('pytest_imports.query'): [
                must_not_import('pytest_imports.parser'),
                must_not_import('pytest_imports.plugin'),
            ],
            scope('pytest_imports.plugin'): must_import('pytest_imports.model'),
            scope('pytest_imports.query'): must_import('pytest_imports.model'),
            scope('pytest_imports.parser'): must_import('pytest_imports.model'),
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
            project(): must_not_import(internal(), via='absolute'),
        }
    )


def test_external_dependencies(imports):
    imports.check(
        {
            scope('pytest_imports', without='parser'): must_not_import('ast'),
            scope('pytest_imports', without='plugin'): must_not_import('pytest'),
        }
    )


def test_no_private_imports(imports):
    imports.check(
        {
            project(): must_not_import_private(),
        }
    )
