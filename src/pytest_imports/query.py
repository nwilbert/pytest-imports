from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, get_args

from .model import DotPath, ImportInModule, ModuleNode, RootNode, Timing


@dataclass(frozen=True)
class Descendants:
    """Target matching the descendants of `path`, excluding `path` itself.

    `without` carves out subtrees, interpreted relative to `path`: each
    entry excludes `path / entry` and its descendants.
    """

    path: str
    without: tuple[str, ...] = ()


@dataclass(frozen=True)
class Internal:
    """Target matching any import resolving inside the configured source roots."""


@dataclass(frozen=True)
class Stdlib:
    """Target matching any non-internal import of a standard library module."""


@dataclass(frozen=True)
class ThirdParty:
    """Target matching any import that is neither internal nor stdlib."""


Target = str | Descendants | Internal | Stdlib | ThirdParty

# The canonical shared `Internal()` instance, used as the default `among`
# universe for `must_only_import`.
INTERNAL = Internal()


def scope(path: str, *, without: str | list[str] | None = None) -> Scope:
    if isinstance(without, str):
        without = [without]
    return Scope(path=path, without=tuple(without or []))


def project() -> Scope:
    """Return a scope covering the entire project."""
    return Scope(path=None)


def descendants(path: str, *, without: str | list[str] | None = None) -> Descendants:
    if isinstance(without, str):
        without = [without]
    return Descendants(path=path, without=tuple(without or []))


def internal() -> Internal:
    return INTERNAL


def stdlib() -> Stdlib:
    return Stdlib()


def third_party() -> ThirdParty:
    return ThirdParty()


def must_import(
    path: Target | list[Target],
    *,
    via: Via | None = None,
    timing: Timing | list[Timing] | None = None,
) -> MustImport:
    return MustImport(
        path=_as_target_tuple(path), via=via, timing=_as_timing_set(timing)
    )


def must_not_import(
    path: Target | list[Target],
    *,
    via: Via | None = None,
    timing: Timing | list[Timing] | None = None,
) -> MustNotImport:
    return MustNotImport(
        path=_as_target_tuple(path), via=via, timing=_as_timing_set(timing)
    )


def must_not_import_private(
    path: Target | list[Target] | None = None,
    *,
    timing: Timing | list[Timing] | None = None,
) -> MustNotImportPrivate:
    return MustNotImportPrivate(
        path=() if path is None else _as_target_tuple(path),
        timing=_as_timing_set(timing),
    )


def must_only_import(
    allowed: Target | list[Target],
    *,
    among: Target = INTERNAL,
    via: Via | None = None,
    timing: Timing | list[Timing] | None = None,
) -> MustOnlyImport:
    # `among` is the bounded universe the allowlist is checked against;
    # it defaults to all internal imports.
    return MustOnlyImport(
        allowed=_as_target_tuple(allowed),
        among=among,
        via=via,
        timing=_as_timing_set(timing),
    )


def must_alias(path: str, alias: str) -> MustAlias:
    return MustAlias(path=path, alias=alias)


def evaluate_rules(
    root_node: RootNode,
    rules: dict[Scope, Predicate | list[Predicate]],
) -> list[str]:
    """Evaluate all rules and return a list of human-readable failure messages."""
    failures: list[str] = []
    for scope_key, predicates in rules.items():
        scope_path = scope_key.path
        exclude: list[DotPath] = [DotPath(s) for s in scope_key.without]
        predicate_list = predicates if isinstance(predicates, list) else [predicates]

        scope_label = '<project>' if scope_path is None else scope_path

        if scope_path is None:
            nodes: list[ModuleNode] = root_node.children()
        else:
            node = root_node.get(DotPath(scope_path)) if scope_path else None
            if not node:
                failures.append(
                    f'  [scope {scope_label}] unknown scope'
                    f' — no module found for path {scope_path}'
                )
                continue
            nodes = [node]

        for node in nodes:
            for predicate in predicate_list:
                _evaluate_predicate(
                    node, exclude, predicate, scope_label, root_node, failures
                )

    return failures


Via = Literal['absolute', 'relative']


@dataclass(frozen=True)
class Scope:
    """The set of modules a rule applies to.

    `path` identifies the module at the root of the scope; the scope
    covers that module and all of its descendants, minus any names
    listed in `without`. `path=None` means the entire project.
    """

    path: str | None = None
    without: tuple[str, ...] = ()


@dataclass(frozen=True)
class MustImport:
    """Predicate asserting that a scope must contain the given imports.

    Multiple targets are conjunctive: each must be matched by some
    import in scope. `timing` restricts which imports count (`None`
    means every timing).
    """

    path: tuple[Target, ...]
    via: Via | None = None
    timing: frozenset[Timing] | None = None


@dataclass(frozen=True)
class MustNotImport:
    """Predicate asserting that a scope must not contain the given imports.

    Multiple targets are disjunctive: an import matching any of them is
    a violation. Imports with a timing outside `timing` are ignored
    (`None` means every timing).
    """

    path: tuple[Target, ...]
    via: Via | None = None
    timing: frozenset[Timing] | None = None


@dataclass(frozen=True)
class MustNotImportPrivate:
    """Predicate asserting that a scope must not import any private name.

    `path` is an optional filter: an empty tuple flags every private
    import, otherwise only private imports matching at least one target
    are flagged. Imports with a timing outside `timing` are ignored
    (`None` means every timing).
    """

    path: tuple[Target, ...] = ()
    timing: frozenset[Timing] | None = None


@dataclass(frozen=True)
class MustOnlyImport:
    """Predicate asserting a scope may only import the `allowed` targets.

    Among the imports matching `among` (the bounded universe, internal
    modules by default), every one must match at least one entry in
    `allowed`; any other is a violation. Imports outside `among`, or
    with a timing outside `timing` (`None` means every timing), are
    ignored.
    """

    allowed: tuple[Target, ...]
    among: Target = INTERNAL
    via: Via | None = None
    timing: frozenset[Timing] | None = None


@dataclass(frozen=True)
class MustAlias:
    """Predicate asserting a package may only enter the namespace under `alias`.

    Namespace-oriented, not statement-oriented: a plain `import <path>`
    must bind the canonical `alias` (`import numpy as np`), and the
    canonical alias must not be bound to a submodule. Non-star
    from-imports (`from numpy import array`) are allowed — they bind only
    the imported member, not the target package. The predicate does not
    require the package to be imported at all; it only constrains how.
    """

    path: str
    alias: str


Predicate = (
    MustImport | MustNotImport | MustNotImportPrivate | MustOnlyImport | MustAlias
)


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
            timing_str = _format_timings(predicate.timing)
            # Conjunctive: every target must be matched by some import.
            for target in predicate.path:
                if not any(
                    _find_matching_imports(
                        node,
                        exclude,
                        target,
                        predicate.via,
                        predicate.timing,
                        root_node,
                    )
                ):
                    failures.append(
                        f'  [scope {scope_label}] must import {_format_target(target)}'
                        f'{timing_str} — no matching import found'
                    )
        case MustNotImport():
            timing_str = _format_timings(predicate.timing)
            # Disjunctive: an import matching any target is a violation.
            multi = len(predicate.path) != 1
            if multi:
                target_str = (
                    '{' + ', '.join(_format_target(t) for t in predicate.path) + '}'
                )
            else:
                target_str = _format_target(predicate.path[0])
            for module_node, import_by, matched in _find_imports_matching_any(
                node,
                exclude,
                predicate.path,
                predicate.via,
                predicate.timing,
                root_node,
            ):
                location = f'{module_node.file_path}:{import_by.line_no}'
                matching = f' matching {_format_target(matched)}' if multi else ''
                failures.append(
                    f'  [scope {scope_label}] must not import {target_str}{timing_str}'
                    f' — found {import_by.dot_path}{matching} in {location}'
                    f'{_format_actual_timing(predicate.timing, import_by)}'
                )
        case MustNotImportPrivate():
            timing_str = _format_timings(predicate.timing)
            if not predicate.path:
                from_str = ''
            elif len(predicate.path) == 1:
                from_str = f' from {_format_target(predicate.path[0])}'
            else:
                targets = ', '.join(_format_target(t) for t in predicate.path)
                from_str = f' from {{{targets}}}'
            for module_node, import_by in _find_matching_private_imports(
                node, exclude, predicate.path, predicate.timing, root_node
            ):
                failures.append(
                    f'  [scope {scope_label}] must not import private names'
                    f'{from_str}{timing_str}'
                    f' — found in {module_node.file_path}:{import_by.line_no}'
                    f'{_format_actual_timing(predicate.timing, import_by)}'
                )
        case MustOnlyImport():
            timing_str = _format_timings(predicate.timing)
            among_str = _format_target(predicate.among)
            allowed_str = (
                '{' + ', '.join(_format_target(t) for t in predicate.allowed) + '}'
            )
            for module_node, import_by in _find_matching_imports(
                node,
                exclude,
                predicate.among,
                predicate.via,
                predicate.timing,
                root_node,
            ):
                if any(
                    _match_target(t, import_by.dot_path, root_node)
                    for t in predicate.allowed
                ):
                    continue
                location = f'{module_node.file_path}:{import_by.line_no}'
                actual_timing = _format_actual_timing(predicate.timing, import_by)
                if predicate.allowed:
                    failures.append(
                        f'  [scope {scope_label}] must only import {allowed_str}'
                        f' among {among_str}{timing_str}'
                        f' — found {import_by.dot_path} in {location}{actual_timing}'
                    )
                else:
                    failures.append(
                        f'  [scope {scope_label}] must not import anything'
                        f' among {among_str}{timing_str}'
                        f' — found {import_by.dot_path} in {location}{actual_timing}'
                    )
        case MustAlias():
            for module_node, import_by in _find_alias_violations(
                node, exclude, predicate.path, predicate.alias
            ):
                location = f'{module_node.file_path}:{import_by.line_no}'
                failures.append(
                    f'  [scope {scope_label}] must import {predicate.path}'
                    f' only as {predicate.alias} — found in {location}'
                )


def _find_matching_imports(
    base_node: ModuleNode,
    exclude: list[DotPath],
    target: Target,
    via: Via | None,
    timings: frozenset[Timing] | None,
    root_node: RootNode,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    for module_node, import_by, _ in _find_imports_matching_any(
        base_node, exclude, (target,), via, timings, root_node
    ):
        yield module_node, import_by


def _find_imports_matching_any(
    base_node: ModuleNode,
    exclude: list[DotPath],
    targets: tuple[Target, ...],
    via: Via | None,
    timings: frozenset[Timing] | None,
    root_node: RootNode,
) -> Iterator[tuple[ModuleNode, ImportInModule, Target]]:
    """Yield each import matching any target, with the first target it matched."""
    absolute = _via_to_absolute(via)
    for module_node in base_node.walk(exclude=exclude):
        for import_by in module_node.imports:
            if absolute is not None and absolute == bool(import_by.level):
                continue
            if timings is not None and import_by.timing not in timings:
                continue
            for target in targets:
                if _match_target(target, import_by.dot_path, root_node):
                    yield module_node, import_by, target
                    break


def _find_matching_private_imports(
    base_node: ModuleNode,
    exclude: list[DotPath],
    path: tuple[Target, ...],
    timings: frozenset[Timing] | None,
    root_node: RootNode,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    for module_node in base_node.walk(exclude=exclude):
        for import_by in module_node.imports:
            if timings is not None and import_by.timing not in timings:
                continue
            if path and not any(
                _match_target(t, import_by.dot_path, root_node) for t in path
            ):
                continue
            if any(_is_private_name(p) for p in import_by.dot_path.parts):
                yield module_node, import_by


def _find_alias_violations(
    base_node: ModuleNode,
    exclude: list[DotPath],
    path: str,
    alias: str,
) -> Iterator[tuple[ModuleNode, ImportInModule]]:
    """Yield each import that binds `path` under a name other than `alias`.

    Only imports whose `dot_path` is relative to `path` are considered;
    see `_is_alias_violation` for the per-import rule.
    """
    target = DotPath(path)
    for module_node in base_node.walk(exclude=exclude):
        for import_by in module_node.imports:
            if not import_by.dot_path.is_relative_to(target):
                continue
            if _is_alias_violation(import_by, target, alias):
                yield module_node, import_by


def _is_alias_violation(import_by: ImportInModule, target: DotPath, alias: str) -> bool:
    if import_by.is_from_import:
        # Non-star from-imports bind only the member, not the target.
        return import_by.dot_path.name == '*'
    if import_by.asname is None:
        # A plain `import` binds the bare top-level package name.
        return True
    if import_by.dot_path == target:
        # The target itself must use the canonical alias.
        return import_by.asname != alias
    # A descendant must not steal the canonical alias.
    return import_by.asname == alias


def _match_target(target: Target, dot_path: DotPath, root_node: RootNode) -> bool:
    match target:
        case str():
            return dot_path.is_relative_to(DotPath(target))
        case Descendants(path=p, without=without):
            tp = DotPath(p)
            if dot_path == tp or not dot_path.is_relative_to(tp):
                return False
            return not any(dot_path.is_relative_to(tp / DotPath(w)) for w in without)
        case Internal():
            return _is_internal(dot_path, root_node)
        # Internal wins over stdlib; the cheap name check runs first so the
        # prefix walk is skipped where the name alone decides.
        case Stdlib():
            return _is_stdlib(dot_path) and not _is_internal(dot_path, root_node)
        case ThirdParty():
            return not _is_stdlib(dot_path) and not _is_internal(dot_path, root_node)


def _is_internal(dot_path: DotPath, root_node: RootNode) -> bool:
    # An import is internal if it resolves to a module under the configured
    # source roots. Because the parser stores the imported name as the last
    # part of `dot_path` (so `from pkg.b import x` yields `pkg.b.x` even when
    # `x` is a symbol, not a submodule), we check whether any prefix of
    # `dot_path` is a known module.
    candidate = dot_path
    while candidate.parts:
        if root_node.get(candidate) is not None:
            return True
        candidate = candidate.parent
    return False


def _is_stdlib(dot_path: DotPath) -> bool:
    # Follows the running interpreter's version (e.g. `annotationlib` is
    # stdlib only on 3.14+), but not its platform: the set lists every platform's
    # modules.
    return dot_path.parts[0] in sys.stdlib_module_names


def _format_target(target: Target) -> str:
    match target:
        case str():
            return target
        case Descendants(path=p, without=without):
            if without:
                return f'descendants of {p} except {{{", ".join(without)}}}'
            return f'descendants of {p}'
        case Internal():
            return 'any internal module'
        case Stdlib():
            return 'any stdlib module'
        case ThirdParty():
            return 'any third-party module'


# All timings, in the order used when joining their labels.
_TIMINGS: tuple[Timing, ...] = get_args(Timing)

# Per timing: the phrase appended to a rule, and the short label of an
# import's actual timing.
_TIMING_LABELS: dict[Timing, tuple[str, str]] = {
    'top': ('at top level', 'top level'),
    'lazy': ('as a lazy import', 'lazy'),
    'function': ('at function level', 'function level'),
    'type_checking': ('in a TYPE_CHECKING block', 'TYPE_CHECKING block'),
}


def _format_timings(timings: frozenset[Timing] | None) -> str:
    """Return the rule's timing phrase with a leading space, or `''` if unset."""
    if timings is None:
        return ''
    return ' ' + ' or '.join(_TIMING_LABELS[t][0] for t in _TIMINGS if t in timings)


def _format_actual_timing(
    timings: frozenset[Timing] | None, import_by: ImportInModule
) -> str:
    """Return ` (<label>)` for the import's timing if the rule names several."""
    if timings is None or len(timings) == 1:
        return ''
    return f' ({_TIMING_LABELS[import_by.timing][1]})'


def _via_to_absolute(via: Via | None) -> bool | None:
    if via == 'absolute':
        return True
    if via == 'relative':
        return False
    return None


def _is_private_name(name: str) -> bool:
    return name.startswith('_') and name != '__future__'


def _as_target_tuple(path: Target | list[Target]) -> tuple[Target, ...]:
    return tuple(path) if isinstance(path, list) else (path,)


def _as_timing_set(
    timing: Timing | list[Timing] | None,
) -> frozenset[Timing] | None:
    if timing is None:
        return None
    timings = frozenset([timing] if isinstance(timing, str) else timing)
    # `Literal` is not enforced at runtime; a typo would otherwise match
    # nothing and make every `must_not_import` rule pass.
    if not timings or not timings.issubset(_TIMINGS):
        raise ValueError(
            f'timing must be one of {", ".join(map(repr, _TIMINGS))},'
            f' or a non-empty list of them; got {timing!r}'
        )
    return timings
