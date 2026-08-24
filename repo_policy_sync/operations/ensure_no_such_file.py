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

"""The ensure_no_such_file operation."""

from pathlib import Path
from typing import Any

from ..errors import RepoPolicySyncError
from ..models import EnsureNoSuchFile, EnsureOperation
from ._validation import (
    expect_keys,
    optional_string,
    required_string,
    safe_relative_path,
)


class EnsureNoSuchFileOperation:
    operation_type = "ensure_no_such_file"
    operation_class = EnsureNoSuchFile

    def parse(self, raw: dict[str, Any], source: Path) -> EnsureNoSuchFile:
        expect_keys(raw, {"type", "path", "rationale"}, source)
        return EnsureNoSuchFile(
            safe_relative_path(required_string(raw, "path", source), source),
            optional_string(raw, "rationale", source),
        )

    def describe_change(self, path: Path, operation: EnsureOperation) -> str | None:
        if path.is_dir():
            assert isinstance(operation, EnsureNoSuchFile)
            raise RepoPolicySyncError(f"refusing to remove directory {operation.path}")
        return "remove file" if path.exists() else None

    def apply(self, path: Path, operation: EnsureOperation) -> None:
        if not path.exists():
            return
        if path.is_dir():
            assert isinstance(operation, EnsureNoSuchFile)
            raise RepoPolicySyncError(f"refusing to remove directory {operation.path}")
        path.unlink()
