from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from .model import RootNode
from .parser import build_import_model
from .query import Predicate, Scope, evaluate_rules

log = logging.getLogger(__name__)

INI_NAME = 'imports_project_paths'
PROJECT_CONFIG_FILES = ['pyproject.toml', 'setup.cfg', 'setup.py']


@pytest.fixture
def imports(imports_root_node: RootNode) -> ImportsFixture:
    """
    Provides the entry point for checking import rules in tests.
    """
    return ImportsFixture(imports_root_node)


class ImportsFixture:
    """Provides import rule checking for test assertions."""

    def __init__(self, imports_root_node: RootNode):
        self._root_node = imports_root_node

    def check(self, rules: dict[str | Scope, Predicate | list[Predicate]]) -> None:
        """
        Check a set of import rules, each mapping a scope to one or more
        predicates.

        Raises AssertionError listing all violations if any rules fail.
        """
        failures = evaluate_rules(self._root_node, rules)
        if failures:
            raise AssertionError('Import rule violations:\n' + '\n'.join(failures))


@pytest.fixture(scope='session')
def imports_root_node(imports_project_paths: Sequence[Path]) -> RootNode:
    """
    Provides the root node of the tree of analyzed Python modules.

    Normally this isn't used explicitly in tests.
    """
    log.info(f'creating import model for {list(imports_project_paths)}')
    return build_import_model(imports_project_paths)


@pytest.fixture(scope='session')
def imports_project_paths(pytestconfig: pytest.Config) -> Sequence[Path]:
    """
    Provides the project source code paths that are analyzed.

    This fixture normally isn't used explicitly in tests, unless you want
    to check that the project paths are set correctly.

    Logic for finding the project path:
     1. If there is an `imports_project_paths` config entry in the pytest config
        then use that and be done.
     2. If there is no config then start with the pytest root path.
     3. Go up until a `pyproject.toml`, `setup.cfg`, or `setup.py` is found.
     4. If there is a `src` directory directly below then use that,
        otherwise use the path from step 3.
    """
    # Note: pytest already converts relative to absolute paths.
    if project_paths := pytestconfig.getini(INI_NAME):
        return project_paths  # type: ignore[no-any-return]
    # Note: pytest considers config files in its rootpath heuristic
    #   only if those files actually contain pytest config.
    for path in (pytestconfig.rootpath, *pytestconfig.rootpath.parents):
        for config_file in PROJECT_CONFIG_FILES:
            if (path / config_file).exists():
                if (src_path := path / 'src').exists():
                    return [src_path]
                return [path]
    return [pytestconfig.rootpath]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        INI_NAME,
        type='paths',
        help='Paths for pytest-imports source code analysis '
        '(relative to rootpath or absolute).',
    )
