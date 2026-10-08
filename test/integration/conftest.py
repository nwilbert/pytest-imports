from inspect import cleandoc
from pathlib import Path

import pytest


def _create_project_on_disk(struct: dict[str, str | dict], current_path: Path):
    for key, value in struct.items():
        path = current_path / key
        match value:
            case dict():
                path.mkdir()
                _create_project_on_disk(value, path)
            case str():
                path.write_text(cleandoc(value))


@pytest.fixture
def project_path(project_structure: dict[str, str | dict], tmp_path: Path) -> Path:
    _create_project_on_disk(project_structure, tmp_path)
    return tmp_path
