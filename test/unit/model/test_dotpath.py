from pathlib import Path

import pytest

from pytest_imports.model import DotPath


@pytest.mark.parametrize(
    ('path', 'parts'),
    [
        (None, ()),
        ('', ()),
        ('aa', ('aa',)),
        ('a.b', ('a', 'b')),
        ('ab.cd.e', ('ab', 'cd', 'e')),
        ('ab..cd', ('ab', '', 'cd')),
        ([], ()),
        (['a', 'b'], ('a', 'b')),
        (DotPath('a.b'), ('a', 'b')),
        (DotPath(''), ()),
    ],
)
def test_dotpath_init(path: str, parts: tuple[str, ...]):
    assert DotPath(path).parts == parts


@pytest.mark.parametrize(
    ('path', 'dotpath'),
    [
        (Path(), DotPath()),
        (Path('aa') / 'bb', DotPath('aa.bb')),
        (Path('a.py'), DotPath('a')),
        (Path('a') / 'b.py', DotPath('a.b')),
        (Path('a') / '__init__.py', DotPath('a')),
        (Path('a.b') / 'c', DotPath(('a.b', 'c'))),
    ],
)
def test_dotpath_from_path(path: Path, dotpath: DotPath):
    assert DotPath.from_path(path) == dotpath


@pytest.mark.parametrize(
    ('path', 'other', 'result'),
    [
        ('', '', True),
        ('a', 'a', True),
        ('a.b', 'a', True),
        ('aa.b', 'aa.b', True),
        ('b.b', 'a.b', False),
        ('a.b', 'b', False),
        ('ab.cd.e', 'ab.cd', True),
        ('e.ab.cd', 'ab.cd', False),
    ],
)
def test_dotpath_is_relative_to(path: str, other: str, result: bool):
    assert DotPath(path).is_relative_to(DotPath(other)) == result


def test_dotpath_name():
    assert DotPath('a.bb').name == 'bb'


def test_dotpath_name_empty():
    assert DotPath().name == ''


@pytest.mark.parametrize(
    ('dotpath', 'parent'),
    [
        (DotPath('aa'), DotPath()),
        (DotPath('aa.bb.cc'), DotPath('aa.bb')),
        (DotPath(), DotPath()),
    ],
)
def test_dotpath_parent(dotpath: DotPath, parent: DotPath):
    assert dotpath.parent == parent


def test_dotpath_str():
    assert str(DotPath('ab.cd.e')) == 'ab.cd.e'


def test_dotpath_repr():
    assert repr(DotPath('ab.cd.e')) == "DotPath(('ab', 'cd', 'e'))"


def test_dotpath_equal():
    assert DotPath('ab.cd.e') == DotPath('ab.cd.e')
    assert DotPath('ab.cd.e') != DotPath('ab.d.e')


def test_dotpath_equal_other_type():
    assert DotPath('ab.cd.e') != 42


def test_dotpath_truediv():
    assert DotPath('a.b') / DotPath('c') == DotPath('a.b.c')
    assert DotPath('a') / 'b' == DotPath('a.b')
    assert 'a' / DotPath('b') == DotPath('a.b')


def test_dotpath_hash():
    assert hash(DotPath('a')) != hash(DotPath('b'))
    assert hash(DotPath('a.b')) == hash(DotPath('a.b'))
    assert hash(DotPath('a.b')) != hash(DotPath('a.c'))


def test_dotpath_hash_stable():
    dp = DotPath('a.b')
    assert hash(dp) == hash(dp)
