# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************

"""Built-in policy operations and their explicit dispatch registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ..models import (
    Change,
    EnsureBazelDependency,
    EnsureOperation,
    MigrateDevcontainerJson,
    SynchronizeBazelDependencies,
    SynchronizeDevcontainerVersion,
)
from .ensure_bazel_dependency import EnsureBazelDependencyOperation
from .ensure_line import EnsureLineOperation
from .ensure_minimum_version import EnsureMinimumVersionOperation
from .ensure_no_such_file import EnsureNoSuchFileOperation
from .migrate_devcontainer_json import MigrateDevcontainerJsonOperation
from .replace_regex import ReplaceRegexOperation
from .synchronize_devcontainer_version import SynchronizeDevcontainerVersionOperation
from .synchronize_bazel_dependencies import SynchronizeBazelDependenciesOperation
from .synchronize_file import SynchronizeFileOperation


class OperationHandler(Protocol):
    operation_type: str

    def parse(self, raw: dict[str, Any], source: Path) -> EnsureOperation: ...

    def describe_change(self, path: Path, operation: EnsureOperation) -> str | None: ...

    def apply(self, path: Path, operation: EnsureOperation) -> None: ...


_HANDLERS: tuple[OperationHandler, ...] = (
    EnsureLineOperation(),
    EnsureMinimumVersionOperation(),
    EnsureNoSuchFileOperation(),
    EnsureBazelDependencyOperation(),
    MigrateDevcontainerJsonOperation(),
    ReplaceRegexOperation(),
    SynchronizeDevcontainerVersionOperation(),
    SynchronizeBazelDependenciesOperation(),
    SynchronizeFileOperation(),
)
# Operations that work on a repository root are handled explicitly below;
# path-based operations can be dispatched directly to one target file.
_BY_TYPE = {handler.operation_type: handler for handler in _HANDLERS}


def parse_operation(raw: object, source: Path) -> EnsureOperation:
    """Parse one operation using the built-in registry."""

    if not isinstance(raw, dict):
        from ..errors import PolicyError

        raise PolicyError(f"policy {source}: each ensure item must be a mapping")
    operation_type = raw.get("type")
    if not isinstance(operation_type, str) or operation_type not in _BY_TYPE:
        from ..errors import PolicyError

        raise PolicyError(
            f"policy {source}: unsupported ensure type {operation_type!r}"
        )
    return _BY_TYPE[operation_type].parse(raw, source)


def describe_changes(
    root: Path, operation: EnsureOperation, *, organization: str | None = None
) -> tuple[Change, ...]:
    """Describe every path an operation would change."""

    handler = _handler_for(operation)
    if isinstance(operation, MigrateDevcontainerJson):
        return handler.describe_changes(root, operation, organization=organization)  # type: ignore[attr-defined]
    if isinstance(operation, EnsureBazelDependency):
        return handler.describe_changes(root, operation)  # type: ignore[attr-defined]
    if isinstance(operation, SynchronizeDevcontainerVersion):
        return handler.describe_changes(root, operation)  # type: ignore[attr-defined]
    if isinstance(operation, SynchronizeBazelDependencies):
        return handler.describe_changes(root, operation)  # type: ignore[attr-defined]
    path = root / operation.path
    description = handler.describe_change(path, operation)
    return (
        (Change(operation.path, description, operation.rationale),)
        if description
        else ()
    )


def apply(
    root: Path, operation: EnsureOperation, *, organization: str | None = None
) -> None:
    """Apply one operation from a repository root."""

    handler = _handler_for(operation)
    if isinstance(operation, MigrateDevcontainerJson):
        handler.apply(root, operation, organization=organization)  # type: ignore[attr-defined]
        return
    if isinstance(operation, EnsureBazelDependency):
        handler.apply(root, operation)  # type: ignore[attr-defined]
        return
    if isinstance(operation, SynchronizeDevcontainerVersion):
        handler.apply(root, operation)
        return
    if isinstance(operation, SynchronizeBazelDependencies):
        handler.apply(root, operation)  # type: ignore[attr-defined]
        return
    handler.apply(root / operation.path, operation)


def _handler_for(operation: EnsureOperation) -> OperationHandler:
    for handler in _HANDLERS:
        if handler.operation_class is type(operation):  # type: ignore[attr-defined]
            return handler
    raise TypeError(f"no operation handler registered for {type(operation).__name__}")
