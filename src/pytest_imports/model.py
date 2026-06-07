from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath


class RootNode:
    """Represents the root of a tree of module nodes."""

    def __init__(self) -> None:
        self._children: dict[str, ModuleNode] = {}

    def children(self) -> list[ModuleNode]:
        """Return the direct children of this node."""
        return list(self._children.values())

    def get(self, dot_path: DotPath) -> ModuleNode | None:
        if not dot_path.parts:
            raise KeyError('Empty path is not supported on root node.')
        if child := self._children.get(dot_path.parts[0]):
            return child.get(DotPath(dot_path.parts[1:]))
        return None

    def get_or_add(self, dot_path: DotPath, file_path: Path) -> ModuleNode:
        if not dot_path.parts:
            raise KeyError('Empty path is not supported on root node.')
        name = dot_path.parts[0]
        remaining_path = DotPath(dot_path.parts[1:])
        if not (child := self._children.get(name)):
            if remaining_path.parts:
                child_file_path = Path(*file_path.parts[: -len(remaining_path.parts)])
            else:
                child_file_path = file_path
            child = ModuleNode(
                name=name,
                full_dotpath=self._child_dotpath(name),
                file_path=child_file_path,
            )
            self._children[name] = child
        return child.get_or_add(remaining_path, file_path)

    def _child_dotpath(self, name: str) -> DotPath:
        return DotPath(name)


class ModuleNode(RootNode):
    """Represents a node in the project's module tree.

    A node typically represents a module — either a `.py` file or a
    package. When the node represents a package, it carries the data
    from that package's `__init__.py`; there is no separate node for
    the `__init__.py` itself.

    A node may also represent an intermediate directory that has no
    `__init__.py` of its own but contains descendant `.py` files.
    Such a node carries no imports.
    """

    def __init__(self, name: str, full_dotpath: DotPath, file_path: Path) -> None:
        super().__init__()
        self._name: str = name
        self._dot_path: DotPath = full_dotpath
        self._file_path: Path = file_path
        self._imports: list[ImportInModule] = []

    @property
    def name(self) -> str:
        """The name of the module or directory.

        The `.py` file extension is not included in the name.
        """
        return self._name

    @property
    def dot_path(self) -> DotPath:
        """The fully qualified dot-separated path of this module."""
        return self._dot_path

    @property
    def imports(self) -> Sequence[ImportInModule]:
        return self._imports

    @property
    def file_path(self) -> Path:
        """Absolute path of the module or directory.

        If this node represents a package with an `__init__.py` file,
        then the `file_path` points to that file.
        """
        return self._file_path

    def get(self, dot_path: DotPath) -> ModuleNode | None:
        """Return the node from this tree corresponding to the dot path."""
        if not dot_path.parts:
            return self
        return super().get(dot_path)

    def get_or_add(self, dot_path: DotPath, file_path: Path) -> ModuleNode:
        """Return the node for this dot_path.

        If this node and any of its parents are missing then they are
        first added to the tree.
        """
        if not dot_path.parts:
            return self
        return super().get_or_add(dot_path, file_path)

    def walk(self, exclude: Iterable[DotPath] | None = None) -> Iterator[ModuleNode]:
        """Return all nodes including and below this node.

        If the exclude argument is used then the given paths are
        expected to be relative to this node.
        """
        yield self
        for child in self._children.values():
            relative_exclude = None
            if exclude:
                relative_exclude = {
                    DotPath(p.parts[1:])
                    for p in exclude
                    if p.parts and p.parts[0] == child.name
                }
                if DotPath() in relative_exclude:
                    continue
            yield from child.walk(exclude=relative_exclude)

    def add_imports(self, imports: Iterable[ImportInModule]) -> None:
        self._imports += imports

    def add_data_for_init_file(self, imports: Iterable[ImportInModule]) -> None:
        """Turn a directory node into a package node,
        with data from the `__init__.py` file.

        There is no separate node for the `__init__.py` file.
        """
        if self._file_path.name != '__init__.py':
            assert not self._file_path.suffix
            self._file_path /= '__init__.py'
        self.add_imports(imports)

    def _child_dotpath(self, name: str) -> DotPath:
        return self._dot_path / name


@dataclass
class ImportInModule:
    """Represents a single import in a module.

    `dot_path` is the fully qualified dotted name of the import target.
    It is always absolute, even when the source statement is a relative
    import — in that case the relativity is recorded separately by
    `level > 0`.
    """

    dot_path: DotPath
    line_no: int
    level: int = 0


class DotPath:
    """
    Represent a 'path' with dot as the separator,
    as it is used for imports in Python.

    Largely follows the Path interface from pathlib.

    A `DotPath` instance is just a sequence of dot-separated parts; on
    its own it carries no commitment to being absolute, relative, or
    non-empty. Interpretation is contextual. The convention in this
    project is that fields and properties *named* `dot_path` (e.g.,
    `ModuleNode.dot_path`, `ImportInModule.dot_path`) always hold a
    fully qualified absolute path. Internal helpers (tree traversal,
    scope exclusions, intermediate parse state) may use `DotPath` for
    relative paths or the empty path; those uses are documented at
    their call sites.
    """

    def __init__(self, path: str | Iterable[str] | DotPath | None = None):
        self._parts: tuple[str, ...]
        self._hash: int | None = None
        match path:
            case None | '' | []:
                self._parts = ()
            case str():
                self._parts = tuple(path.split('.'))
            case DotPath():
                self._parts = path.parts
            case _:
                self._parts = tuple(path)

    @classmethod
    def from_path(cls, path: PurePath) -> DotPath:
        parts = list(path.parts)
        if len(parts) == 0:
            return DotPath()
        if parts[-1] == '__init__.py':
            parts.pop()
        else:
            parts[-1] = parts[-1].removesuffix('.py')
        return cls(parts)

    @property
    def parts(self) -> tuple[str, ...]:
        return self._parts

    @property
    def name(self) -> str:
        return self._parts[-1]

    @property
    def parent(self) -> DotPath:
        return DotPath(self._parts[:-1])

    def is_relative_to(self, other: DotPath) -> bool:
        if len(other.parts) > len(self.parts):
            return False
        return other.parts == self.parts[: len(other.parts)]

    def __str__(self) -> str:
        return '.'.join(self._parts)

    def __repr__(self) -> str:
        return f'{type(self).__name__}({self.parts})'

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(tuple(self._parts))
        return self._hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DotPath):
            return NotImplemented
        return self._parts == other._parts

    def __truediv__(self, other: DotPath | str) -> DotPath:
        return DotPath(self.parts + DotPath(other).parts)

    def __rtruediv__(self, other: DotPath | str) -> DotPath:
        return DotPath(DotPath(other).parts + self.parts)
