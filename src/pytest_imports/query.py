from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from .model import DotPath, ImportInModule, ModuleNode, RootNode

Via = Literal['absolute', 'relative']


@dataclass(frozen=True)
class Scope:
    """A module scope (package or module) to be checked for imports.

    path=None means the entire project (all modules).
    """

    path: str | None = None
    without: tuple[str, ...] = ()


def scope(path: str, *, without: str | list[str] | None = None) -> Scope:
    if isinstance(without, str):
        without = [without]
    return Scope(path=path, without=tuple(without or []))


def project() -> Scope:
    """Return a scope covering the entire project."""
    return Scope(path=None)


@dataclass(frozen=True)
class MustImport:
    """Predicate asserting that a scope must contain a given import."""

    path: str
    via: Via | None = None


def must_import(path: str, *, via: Via | None = None) -> MustImport:
    return MustImport(path=path, via=via)


@dataclass(frozen=True)
class MustNotImport:
    """Predicate asserting that a scope must not contain a given import."""

    path: str
    via: Via | None = None


def must_not_import(path: str, *, via: Via | None = None) -> MustNotImport:
    return MustNotImport(path=path, via=via)


@dataclass(frozen=True)
class MustNotImportPrivate:
    """Predicate asserting that a scope must not import any private symbol."""

    path: str | None = None


def must_not_import_private(path: str | None = None) -> MustNotImportPrivate:
    return MustNotImportPrivate(path=path)


@dataclass(frozen=True)
class MustNotImportWithinParent:
    """Predicate asserting that a scope must not import from its immediate
    parent package using the specified import style (absolute or relative)."""

    via: Via


def must_not_import_within_parent(*, via: Via) -> MustNotImportWithinParent:
    return MustNotImportWithinParent(via=via)


Predicate = (
    MustImport | MustNotImport | MustNotImportPrivate | MustNotImportWithinParent
)


def evaluate_rules(
    root_node: RootNode,
    rules: dict[str | Scope, Predicate | list[Predicate]],
) -> list[str]:
    """Evaluate all rules and return a list of human-readable failure messages."""
    failures: list[str] = []
    for scope_key, predicates in rules.items():
        match scope_key:
            case str():
                scope_path = scope_key
                exclude: list[DotPath] = []
            case Scope(path=scope_path, without=without):
                exclude = [DotPath(s) for s in without]
        predicate_list = predicates if isinstance(predicates, list) else [predicates]

        if scope_path is None:
            nodes: list[ModuleNode] = root_node.children()
        else:
            node = root_node.get(DotPath(scope_path))
            if not node:
                raise KeyError(f'Found no node for path {scope_path} in project.')
            nodes = [node]

        scope_label = scope_path or '<project>'

        for node in nodes:
            for predicate in predicate_list:
                _evaluate_predicate(node, exclude, predicate, scope_label, failures)

    return failures


def _evaluate_predicate(
    node: ModuleNode,
    exclude: list[DotPath],
    predicate: Predicate,
    scope_label: str,
    failures: list[str],
) -> None:
    match predicate:
        case MustImport():
            target_path = DotPath(predicate.path)
            if not any(
                _find_matching_imports(node, exclude, target_path, predicate.via)
            ):
                for module_node in node.walk(exclude=exclude):
                    if module_node.file_path.suffix == '.py':
                        failures.append(
                            f'  [scope {scope_label}] must import {predicate.path}'
                            f' — no matching import in {module_node.file_path}'
                        )
        case MustNotImport():
            target_path = DotPath(predicate.path)
            for module_node, import_by in _find_matching_imports(
                node, exclude, target_path, predicate.via
            ):
                failures.append(
                    f'  [scope {scope_label}] must not import {predicate.path}'
                    f' — found in {module_node.file_path}:{import_by.line_no}'
                )
        case MustNotImportPrivate():
            for module_node, import_by in _find_matching_private_imports(
                node, exclude, predicate.path
            ):
                failures.append(
                    f'  [scope {scope_label}] must not import private symbols'
                    + (f' from {predicate.path}' if predicate.path else '')
                    + f' — found in {module_node.file_path}:{import_by.line_no}'
                )
        case MustNotImportWithinParent():
            for module_node, import_by in _find_within_parent_imports(
                node, exclude, predicate.via
            ):
                failures.append(
                    f'  [scope {scope_label}] must not use {predicate.via} import'
                    f' within parent package'
                    f' — found in {module_node.file_path}:{import_by.line_no}'
                )


def _find_matching_imports(
    base_node: ModuleNode,
    exclude: list[DotPath],
    target_path: DotPath,
    via: Via | None,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    absolute = _via_to_absolute(via)
    for module_node in base_node.walk(exclude=exclude):
        for import_by in module_node.imports:
            if import_by.dot_path.is_relative_to(target_path) and (
                absolute is None or absolute != bool(import_by.level)
            ):
                yield module_node, import_by


def _find_within_parent_imports(
    base_node: ModuleNode,
    exclude: list[DotPath],
    via: Via,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    absolute = via == 'absolute'
    for module_node in base_node.walk(exclude=exclude):
        parent = module_node.dot_path.parent
        if not parent.parts:
            continue  # top-level modules have no parent package to check
        for import_by in module_node.imports:
            if import_by.dot_path.is_relative_to(parent) and absolute != bool(
                import_by.level
            ):
                yield module_node, import_by


def _find_matching_private_imports(
    base_node: ModuleNode,
    exclude: list[DotPath],
    path: str | None,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    filter_path = DotPath(path) if path else None
    for module_node in base_node.walk(exclude=exclude):
        for import_by in module_node.imports:
            if filter_path and not import_by.dot_path.is_relative_to(filter_path):
                continue
            if any(_is_private_name(p) for p in import_by.dot_path.parts):
                yield module_node, import_by


def _is_private_name(name: str) -> bool:
    return name.startswith('_') and name != '__future__'


def _via_to_absolute(via: Via | None) -> bool | None:
    if via == 'absolute':
        return True
    if via == 'relative':
        return False
    return None
