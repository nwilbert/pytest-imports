"""Benchmark configuration for running pytest-imports against Django.

The Django source tree is expected at `benchmark/django/` (gitignored,
sibling to this file). The nox `benchmark` session bootstraps it at the
pinned commit.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from pytest_imports.model import RootNode
from pytest_imports.parser import build_import_model

CHECKOUT_ROOT = Path(__file__).resolve().parent / 'django'

# Keep pytest from descending into the Django checkout when it sits
# alongside this conftest.
collect_ignore = ['django']
# Source root is the checkout root so dotted paths come out as
# `django.X`, `tests.X`, etc. — this includes Django's own test suite
# (~2k files), which makes the benchmark closer to a realistic large
# code base.
SOURCE_ROOTS = [CHECKOUT_ROOT]


def pytest_configure(config: pytest.Config) -> None:
    if not (CHECKOUT_ROOT / 'django' / '__init__.py').exists():
        pytest.exit(
            f'Django checkout not found at {CHECKOUT_ROOT}. '
            f'Run `uv run nox -s benchmark` to bootstrap it.'
        )


def _checkout_head() -> str:
    """Return the short SHA of the checkout's HEAD."""
    return subprocess.run(
        ['git', '-C', str(CHECKOUT_ROOT), 'rev-parse', '--short=12', 'HEAD'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture(scope='session')
def imports_project_paths() -> list[Path]:
    return SOURCE_ROOTS


@pytest.fixture(scope='session')
def imports_root_node(
    imports_project_paths: list[Path], request: pytest.FixtureRequest
) -> RootNode:
    start = time.perf_counter()
    root = build_import_model(imports_project_paths)
    build_seconds = time.perf_counter() - start

    n_modules = 0
    n_imports = 0
    for child in root.children():
        for node in child.walk():
            n_modules += 1
            n_imports += len(node.imports)

    tw = request.config.get_terminal_writer()
    tw.line('')
    tw.line(f'[benchmark] target:        {CHECKOUT_ROOT.name} @ {_checkout_head()}')
    tw.line(f'[benchmark] source roots:  {[str(p) for p in imports_project_paths]}')
    tw.line(f'[benchmark] model build:   {build_seconds:.3f} s')
    tw.line(f'[benchmark] modules:       {n_modules}')
    tw.line(f'[benchmark] imports:       {n_imports}')
    tw.line('')
    return root
