import webbrowser
from pathlib import Path

import nox

src_path = 'src'
code_paths = [src_path, 'test', 'noxfile.py']

nox.options.default_venv_backend = 'uv'
nox.options.reuse_existing_virtualenvs = True
nox.options.sessions = [
    'format',
    'lint',
    'mypy',
    'test',
    'coverage',
    'audit',
]


_SYNC_FLAGS = ('--locked', '--active')


def _sync(session: nox.Session, *groups: str, include_project: bool = False) -> None:
    if include_project:
        group_args = [arg for group in groups for arg in ('--group', group)]
        session.run(
            'uv',
            'sync',
            '--no-default-groups',
            *group_args,
            *_SYNC_FLAGS,
            external=True,
        )
    else:
        group_args = [arg for group in groups for arg in ('--only-group', group)]
        session.run(
            'uv',
            'sync',
            *group_args,
            *_SYNC_FLAGS,
            '--no-install-project',
            external=True,
        )


@nox.session(name='format')
def format_code(session: nox.Session) -> None:
    if session.posargs:
        session.error('format takes no arguments; `lint` is the read-only check')
    _sync(session, 'lint')
    session.run('ruff', 'check', '--select', 'I', '--fix', *code_paths)
    session.run('ruff', 'format', *code_paths)


@nox.session
def lint(session: nox.Session) -> None:
    """The read-only gate: lint rules, then formatting drift. `format` fixes both."""
    _sync(session, 'lint')
    session.run('ruff', 'check', *code_paths)
    session.run('ruff', 'format', '--check', *code_paths)


@nox.session
def mypy(session: nox.Session) -> None:
    _sync(session, 'typecheck', include_project=True)
    session.run('mypy', src_path, 'noxfile.py')


@nox.session
def test(session: nox.Session) -> None:
    _sync(session, 'test', include_project=True)
    session.run('pytest')


PYTEST_PYTHON_MATRIX = [
    ('7', ['3.10', '3.11', '3.12']),
    ('8', ['3.10', '3.11', '3.12', '3.13']),
    ('9', ['3.10', '3.11', '3.12', '3.13', '3.14']),
]


@nox.session
@nox.parametrize(
    'python,pytest_version',
    [
        (python, pytest_ver)
        for pytest_ver, pythons in PYTEST_PYTHON_MATRIX
        for python in pythons
    ],
)
def pytest_compat(session: nox.Session, pytest_version: str) -> None:
    _sync(session, 'test', include_project=True)
    session.run('uv', 'pip', 'install', f'pytest~={pytest_version}.0', external=True)
    session.run('pytest', 'test/integration')


@nox.session
def coverage(session: nox.Session) -> None:
    _sync(session, 'coverage', include_project=True)
    session.run(
        'coverage',
        'run',
        '--source',
        'pytest_imports',
        '-m',
        'pytest',
        'test/integration',
        'test/unit',
    )
    try:
        session.run('coverage', 'report', '--fail-under', '100', '--show-missing')
    finally:
        if 'html' in session.posargs:
            session.run('coverage', 'html', '--skip-covered')
            webbrowser.open((Path.cwd() / 'htmlcov' / 'index.html').as_uri())


@nox.session
def audit(session: nox.Session) -> None:
    # Not _sync: pip-audit needs every declared group plus the project.
    session.run(
        'uv',
        'sync',
        '--all-groups',
        *_SYNC_FLAGS,
        external=True,
    )
    session.run('pip-audit', '--local')


BENCHMARK_REPO = 'https://github.com/django/django.git'
BENCHMARK_COMMIT = '9e7cc2b628fe8fd3895986af9b7fc9525034c1b0'  # Django 5.2
BENCHMARK_CHECKOUT = Path('benchmark') / 'django'


@nox.session
def benchmark(session: nox.Session) -> None:
    """Run pytest-imports against a pinned Django checkout and report timings."""
    _sync(session, 'test', include_project=True)
    _ensure_benchmark_checkout(session)
    session.run(
        'pytest',
        '-s',
        '-v',
        '--durations=0',
        '--no-header',
        'benchmark',
        *session.posargs,
    )


def _ensure_benchmark_checkout(session: nox.Session) -> None:
    # Shallow fetch of a specific commit (rather than a tag) so the
    # pinned revision is part of the contract, not the upstream tag.
    if (BENCHMARK_CHECKOUT / '.git').exists():
        head = str(
            session.run(
                'git',
                '-C',
                str(BENCHMARK_CHECKOUT),
                'rev-parse',
                'HEAD',
                external=True,
                silent=True,
            )
        ).strip()
        if head == BENCHMARK_COMMIT:
            session.log(
                f'Reusing existing checkout at {BENCHMARK_CHECKOUT} (HEAD {head[:12]})'
            )
            return
        session.log(
            f'Updating {BENCHMARK_CHECKOUT} from {head[:12]} to {BENCHMARK_COMMIT[:12]}'
        )
    else:
        BENCHMARK_CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
        session.log(
            f'Fetching {BENCHMARK_REPO}@{BENCHMARK_COMMIT[:12]} '
            f'into {BENCHMARK_CHECKOUT}'
        )
        session.run('git', 'init', str(BENCHMARK_CHECKOUT), external=True)
        session.run(
            'git',
            '-C',
            str(BENCHMARK_CHECKOUT),
            'remote',
            'add',
            'origin',
            BENCHMARK_REPO,
            external=True,
        )
    session.run(
        'git',
        '-C',
        str(BENCHMARK_CHECKOUT),
        'fetch',
        '--depth',
        '1',
        'origin',
        BENCHMARK_COMMIT,
        external=True,
    )
    session.run(
        'git',
        '-C',
        str(BENCHMARK_CHECKOUT),
        'checkout',
        'FETCH_HEAD',
        external=True,
    )
