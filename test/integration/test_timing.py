from inspect import cleandoc
from pathlib import Path

import pytest

from pytest_imports import internal, must_import, must_not_import, scope, third_party
from pytest_imports.parser import build_import_model
from pytest_imports.plugin import ImportsFixture

_BOOTSTRAP = """
    from typing import TYPE_CHECKING
    __lazy_modules__ = ['requests']
    import requests
    import pandas
    if TYPE_CHECKING:
        from .types import T
    def go():
        from .heavy import H
"""


@pytest.fixture
def imports(tmp_path: Path) -> ImportsFixture:
    """A package on disk with one import of each timing in `pkg.bootstrap`."""
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('import os')
    (pkg / 'bootstrap.py').write_text(cleandoc(_BOOTSTRAP))
    (pkg / 'types.py').write_text('')
    (pkg / 'heavy.py').write_text('')
    return ImportsFixture(build_import_model([tmp_path]))


def test_function_level_internal_import_is_reported(imports, tmp_path):
    failures = imports.violations(
        {scope('pkg'): must_not_import(internal(), timing='function')}
    )
    assert failures == [
        '  [scope pkg] must not import any internal module at function level'
        f' — found pkg.heavy.H in {tmp_path / "pkg" / "bootstrap.py"}:8'
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
