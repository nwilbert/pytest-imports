from pathlib import Path

import pytest

from pytest_imports import internal, must_import, must_not_import, scope, third_party
from pytest_imports.parser import build_import_model
from pytest_imports.plugin import ImportsFixture

# A package on disk with one import of each timing in `pkg.bootstrap`.
pytestmark = pytest.mark.parametrize(
    'project_structure',
    [
        {
            'pkg': {
                '__init__.py': 'import os',
                'bootstrap.py': """
                    from typing import TYPE_CHECKING
                    __lazy_modules__ = ['requests']
                    import requests
                    import pandas
                    if TYPE_CHECKING:
                        from .types import T
                    def go():
                        from .heavy import H
                """,
                'types.py': '',
                'heavy.py': '',
            }
        }
    ],
)


@pytest.fixture
def imports(project_path: Path) -> ImportsFixture:
    return ImportsFixture(build_import_model([project_path]))


def test_function_level_internal_import_is_reported(imports, project_path):
    failures = imports.violations(
        {scope('pkg'): must_not_import(internal(), timing='function')}
    )
    assert failures == [
        '  [scope pkg] must not import any internal module at function level'
        f' — found pkg.heavy.H in {project_path / "pkg" / "bootstrap.py"}:8'
    ]


def test_type_checking_import_satisfies_must_import(imports):
    imports.check(
        {scope('pkg.bootstrap'): must_import('pkg.types', timing='type_checking')}
    )


def test_top_level_third_party_import_is_reported(imports):
    failures = imports.violations(
        {scope('pkg.bootstrap'): must_not_import(third_party(), timing='top')}
    )
    assert len(failures) == 1
    assert 'found pandas in' in failures[0]


def test_lazy_modules_import_is_lazy_on_every_interpreter(imports):
    imports.check({scope('pkg.bootstrap'): must_import('requests', timing='lazy')})
