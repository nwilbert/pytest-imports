from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from .model import DotPath, ImportInModule, ModuleNode, RootNode


def scope(path: str, *, without: str | list[str] | None = None) -> Scope:
    if isinstance(without, str):
        without = [without]
    return Scope(path=path, without=tuple(without or []))


def project() -> Scope:
    """Return a scope covering the entire project."""
    return Scope(path=None)


def descendants(path: str) -> Descendants:
    return Descendants(path=path)


def internal() -> Internal:
    return Internal()


def must_import(path: Target, *, via: Via | None = None) -> MustImport:
    return MustImport(path=path, via=via)


def must_not_import(path: Target, *, via: Via | None = None) -> MustNotImport:
    return MustNotImport(path=path, via=via)


def must_not_import_private(path: str | None = None) -> MustNotImportPrivate:
    return MustNotImportPrivate(path=path)


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
                _evaluate_predicate(
                    node, exclude, predicate, scope_label, root_node, failures
                )

    return failures


Via = Literal['absolute', 'relative']


@dataclass(frozen=True)
class Scope:
    """A module scope (package or module) to be checked for imports.

    path=None means the entire project (all modules).
    """

    path: str | None = None
    without: tuple[str, ...] = ()


@dataclass(frozen=True)
class Descendants:
    """Target matching the descendants of `path`, excluding `path` itself."""

    path: str


@dataclass(frozen=True)
class Internal:
    """Target matching any import resolving inside the configured source roots."""


Target = str | Descendants | Internal


@dataclass(frozen=True)
class MustImport:
    """Predicate asserting that a scope must contain a given import."""

    path: Target
    via: Via | None = None


@dataclass(frozen=True)
class MustNotImport:
    """Predicate asserting that a scope must not contain a given import."""

    path: Target
    via: Via | None = None


@dataclass(frozen=True)
class MustNotImportPrivate:
    """Predicate asserting that a scope must not import any private symbol."""

    path: str | None = None


Predicate = MustImport | MustNotImport | MustNotImportPrivate


def _evaluate_predicate(
    node: ModuleNode,
    exclude: list[DotPath],
    predicate: Predicate,
    scope_label: str,
    root_node: RootNode,
    failures: list[str],
) -> None:
    match predicate:
        case MustImport():
            target_str = _format_target(predicate.path)
            if not any(
                _find_matching_imports(
                    node, exclude, predicate.path, predicate.via, root_node
                )
            ):
                for module_node in node.walk(exclude=exclude):
                    if module_node.file_path.suffix == '.py':
                        failures.append(
                            f'  [scope {scope_label}] must import {target_str}'
                            f' — no matching import in {module_node.file_path}'
                        )
        case MustNotImport():
            target_str = _format_target(predicate.path)
            for module_node, import_by in _find_matching_imports(
                node, exclude, predicate.path, predicate.via, root_node
            ):
                location = f'{module_node.file_path}:{import_by.line_no}'
                if isinstance(predicate.path, str):
                    failures.append(
                        f'  [scope {scope_label}] must not import {target_str}'
                        f' — found in {location}'
                    )
                else:
                    failures.append(
                        f'  [scope {scope_label}] must not import {target_str}'
                        f' — found {import_by.dot_path} in {location}'
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


def _find_matching_imports(
    base_node: ModuleNode,
    exclude: list[DotPath],
    target: Target,
    via: Via | None,
    root_node: RootNode,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    absolute = _via_to_absolute(via)
    for module_node in base_node.walk(exclude=exclude):
        for import_by in module_node.imports:
            if _match_target(target, import_by.dot_path, root_node) and (
                absolute is None or absolute != bool(import_by.level)
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


def _match_target(target: Target, dot_path: DotPath, root_node: RootNode) -> bool:
    match target:
        case str():
            return dot_path.is_relative_to(DotPath(target))
        case Descendants(path=p):
            tp = DotPath(p)
            return dot_path != tp and dot_path.is_relative_to(tp)
        case Internal():
            # An import is internal if it resolves to a module under the
            # configured source roots. Because the parser stores the imported
            # name as the last part of `dot_path` (so `from pkg.b import x`
            # yields `pkg.b.x` even when `x` is a symbol, not a submodule), we
            # check whether any prefix of `dot_path` is a known module.
            candidate = dot_path
            while candidate.parts:
                if root_node.get(candidate) is not None:
                    return True
                candidate = candidate.parent
            return False


def _format_target(target: Target) -> str:
    match target:
        case str():
            return target
        case Descendants(path=p):
            return f'descendants of {p}'
        case Internal():
            return 'any internal module'


def _via_to_absolute(via: Via | None) -> bool | None:
    if via == 'absolute':
        return True
    if via == 'relative':
        return False
    return None


def _is_private_name(name: str) -> bool:
    return name.startswith('_') and name != '__future__'
