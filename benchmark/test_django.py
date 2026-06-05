"""Benchmark suite: pytest-imports against the Django source tree.

Each test exercises a different rule shape so that per-test durations
(via ``pytest --durations=0``) show where time is spent. The model is
built once per session and the build time is printed by the
``imports`` fixture in this directory's ``conftest.py``.

These tests do **not** assert; they call ``imports.violations`` and
report ``(time, violation count)`` for each rule. Violations are real
Django couplings — interesting findings, but not what we're measuring.
The goal is timing, so the session always passes and the
``[benchmark]`` lines are the data.
"""

from __future__ import annotations

import time

import pytest

from pytest_imports import (
    descendants,
    internal,
    must_import,
    must_not_import,
    must_not_import_private,
    project,
    scope,
)
from pytest_imports.plugin import ImportsFixture
from pytest_imports.query import Predicate, Scope


def _report(
    label: str,
    imports: ImportsFixture,
    rules: dict[str | Scope, Predicate | list[Predicate]],
) -> int:
    start = time.perf_counter()
    failures = imports.violations(rules)
    elapsed = time.perf_counter() - start
    print(f'\n[benchmark] {label}: {elapsed:.3f} s  ({len(failures)} violations)')
    return len(failures)


# ---------------------------------------------------------------------------
# Realistic layered-architecture rules — the kind a Django project might
# enforce. Reported here, not asserted.
# ---------------------------------------------------------------------------


def test_utils_is_foundational(imports):
    _report(
        'scope(django.utils) must_not_import(<higher layers>)',
        imports,
        {
            scope('django.utils'): [
                must_not_import('django.db'),
                must_not_import('django.template'),
                must_not_import('django.forms'),
                must_not_import('django.views'),
                must_not_import('django.urls'),
                must_not_import('django.contrib'),
            ],
        },
    )


def test_db_below_presentation(imports):
    _report(
        'scope(django.db) must_not_import(<presentation layers>)',
        imports,
        {
            scope('django.db'): [
                must_not_import('django.template'),
                must_not_import('django.forms'),
                must_not_import('django.views'),
                must_not_import('django.urls'),
                must_not_import('django.contrib'),
            ],
        },
    )


def test_template_does_not_depend_on_contrib(imports):
    _report(
        'scope(django.template) must_not_import(django.contrib)',
        imports,
        {scope('django.template'): must_not_import('django.contrib')},
    )


def test_core_does_not_depend_on_contrib(imports):
    _report(
        "scope(django, without='contrib') must_not_import(django.contrib)",
        imports,
        {scope('django', without='contrib'): must_not_import('django.contrib')},
    )


def test_descendants_target(imports):
    _report(
        'scope(django, without=[db,contrib]) '
        'must_not_import(descendants(django.db.migrations))',
        imports,
        {
            scope('django', without=['db', 'contrib']): must_not_import(
                descendants('django.db.migrations')
            ),
        },
    )


def test_dispatch_self_contained(imports):
    _report(
        'scope(django.dispatch) must_not_import(<everything else in django>)',
        imports,
        {
            scope('django.dispatch'): [
                must_not_import('django.db'),
                must_not_import('django.template'),
                must_not_import('django.forms'),
                must_not_import('django.contrib'),
                must_not_import('django.urls'),
                must_not_import('django.views'),
            ],
        },
    )


# ---------------------------------------------------------------------------
# Project-wide stress tests — these touch every module / every import
# in the model.
# ---------------------------------------------------------------------------


def test_stress_project_must_not_import_nothing(imports):
    """Walk every module in the project looking for an impossible import."""
    _report(
        'project() must_not_import(<nonexistent>)',
        imports,
        {project(): must_not_import('this_package_does_not_exist')},
    )


def test_stress_project_must_not_import_private(imports):
    """Whole-project private-import scan."""
    _report(
        'project() must_not_import_private(django)',
        imports,
        {project(): must_not_import_private('django')},
    )


def test_stress_project_internal_absolute(imports):
    """`internal()` target walks every import prefix against the module tree."""
    _report(
        "project() must_not_import(internal(), via='absolute')",
        imports,
        {project(): must_not_import(internal(), via='absolute')},
    )


def test_stress_project_must_import_django(imports):
    """`must_import` scans every file in scope until it finds a hit."""
    _report(
        'project() must_import(django)',
        imports,
        {project(): must_import('django')},
    )


@pytest.mark.parametrize(
    ('label', 'predicate_factory'),
    [
        ('string target', lambda: must_not_import('django.contrib')),
        ('descendants target', lambda: must_not_import(descendants('django.contrib'))),
        ('internal target', lambda: must_not_import(internal())),
    ],
)
def test_stress_target_shapes(imports, label, predicate_factory):
    """Compare the three target shapes on the same wide scope."""
    _report(
        f'scope(django) must_not_import(...) — {label}',
        imports,
        {scope('django'): predicate_factory()},
    )
