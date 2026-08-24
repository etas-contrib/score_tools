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

"""Migrate an image-based devcontainer configuration to a Dockerfile."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..errors import RepoPolicySyncError
from ..models import Change, EnsureOperation, MigrateDevcontainerJson
from ._validation import (
    expect_keys,
    optional_string,
    required_string,
    safe_relative_path,
    string_list,
)

_VERSION = re.compile(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_DOCKERFILE_COMMENT = (
    "# Use Dockerfile to get dependabot version bumps after new image is released"
)
_ECLIPSE_COPYRIGHT = """# *******************************************************************************
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
"""
_IMAGE_PROPERTY = re.compile(
    r'(?m)^(?P<indent>[ \t]*)"image"\s*:\s*"(?P<image>[^"]+)"'
    r"(?P<comma>,?)(?P<tail>[ \t]*(?://[^\r\n]*)?(?:\r?\n|$))"
)


class MigrateDevcontainerJsonOperation:
    operation_type = "migrate_devcontainer_json"
    operation_class = MigrateDevcontainerJson

    def parse(self, raw: dict[str, Any], source: Path) -> MigrateDevcontainerJson:
        expect_keys(
            raw,
            {
                "type",
                "sources",
                "destination",
                "dockerfile",
                "image",
                "rationale",
                "copyright_organization",
            },
            source,
        )
        return MigrateDevcontainerJson(
            sources=tuple(
                safe_relative_path(item, source)
                for item in string_list(raw.get("sources"), "sources", source)
            ),
            destination=safe_relative_path(
                required_string(raw, "destination", source), source
            ),
            dockerfile=safe_relative_path(
                required_string(raw, "dockerfile", source), source
            ),
            image=required_string(raw, "image", source),
            rationale=optional_string(raw, "rationale", source),
            copyright_organization=optional_string(
                raw, "copyright_organization", source
            ),
        )

    def describe_changes(
        self, root: Path, operation: EnsureOperation, *, organization: str | None = None
    ) -> tuple[Change, ...]:
        assert isinstance(operation, MigrateDevcontainerJson)
        source_relative, source = _find_source(root, operation)
        if source is None:
            return ()
        dockerfile = root / operation.dockerfile
        migration = _migration_contents(source, operation, organization)
        if migration is None:
            return ()
        dockerfile_contents, destination_contents = migration
        _validate_target(dockerfile, operation)
        destination = root / operation.destination
        _validate_destination(destination, operation)
        changes: list[Change] = []
        if not dockerfile.exists():
            changes.append(
                Change(operation.dockerfile, "add Dockerfile", operation.rationale)
            )
        elif dockerfile.read_text(encoding="utf-8") != dockerfile_contents:
            raise RepoPolicySyncError(
                f"refusing to overwrite existing {operation.dockerfile} during migration"
            )
        if not destination.exists():
            changes.append(
                Change(
                    operation.destination,
                    "add devcontainer configuration",
                    operation.rationale,
                )
            )
        elif (
            source != destination
            and destination.read_text(encoding="utf-8") != destination_contents
        ):
            raise RepoPolicySyncError(
                f"refusing to overwrite existing {operation.destination} during migration"
            )
        elif (
            source == destination
            and source.read_text(encoding="utf-8") != destination_contents
        ):
            changes.append(
                Change(
                    operation.destination,
                    "configure the devcontainer to build the Dockerfile",
                    operation.rationale,
                )
            )
        if source != destination:
            changes.append(
                Change(
                    source_relative,
                    "move devcontainer configuration",
                    operation.rationale,
                )
            )
        return tuple(changes)

    def apply(
        self, root: Path, operation: EnsureOperation, *, organization: str | None = None
    ) -> None:
        assert isinstance(operation, MigrateDevcontainerJson)
        _, source = _find_source(root, operation)
        if source is None:
            return
        dockerfile = root / operation.dockerfile
        migration = _migration_contents(source, operation, organization)
        if migration is None:
            return
        dockerfile_contents, destination_contents = migration
        _validate_target(dockerfile, operation)
        destination = root / operation.destination
        _validate_destination(destination, operation)
        if (
            dockerfile.exists()
            and dockerfile.read_text(encoding="utf-8") != dockerfile_contents
        ):
            raise RepoPolicySyncError(
                f"refusing to overwrite existing {operation.dockerfile} during migration"
            )
        if (
            destination.exists()
            and source != destination
            and destination.read_text(encoding="utf-8") != destination_contents
        ):
            raise RepoPolicySyncError(
                f"refusing to overwrite existing {operation.destination} during migration"
            )
        if not dockerfile.exists():
            dockerfile.parent.mkdir(parents=True, exist_ok=True)
            dockerfile.write_text(dockerfile_contents, encoding="utf-8")
        if not destination.exists() or source == destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(destination_contents, encoding="utf-8")
        if source != destination:
            source.unlink()


def _find_source(
    root: Path, operation: MigrateDevcontainerJson
) -> tuple[Path | None, Path | None]:
    matches = tuple(
        (path, root / path) for path in operation.sources if (root / path).exists()
    )
    if len(matches) > 1:
        paths = ", ".join(str(path) for path, _ in matches)
        raise RepoPolicySyncError(
            f"only one devcontainer configuration may exist; found {paths}"
        )
    return matches[0] if matches else (None, None)


def _migration_contents(
    source: Path, operation: MigrateDevcontainerJson, organization: str | None
) -> tuple[str, str] | None:
    if not source.is_file():
        raise RepoPolicySyncError(f"{source} must be a file")
    text = source.read_text(encoding="utf-8")
    try:
        configuration = json.loads(_strip_jsonc(text))
    except json.JSONDecodeError as exc:
        raise RepoPolicySyncError(
            f"{source} must contain valid JSONC: {exc.msg}"
        ) from exc
    if not isinstance(configuration, dict):
        raise RepoPolicySyncError(f"{source} must contain a JSON object")
    image = configuration.get("image")
    prefix = f"{operation.image}:"
    if not isinstance(image, str) or not image.startswith(prefix):
        return None
    tag = image.removeprefix(prefix)
    if not tag or _VERSION.fullmatch(tag) is None:
        raise RepoPolicySyncError(
            f"{source} must use {operation.image}:vX.Y.Z, found {tag!r}"
        )
    matches = [
        match
        for match in _IMAGE_PROPERTY.finditer(text)
        if match.group("image") == image
    ]
    if len(matches) != 1:
        raise RepoPolicySyncError(
            f"{source} must contain exactly one top-level image property"
        )
    match = matches[0]
    indent = match.group("indent")
    dockerfile = json.dumps(
        os.path.relpath(operation.dockerfile, operation.destination.parent).replace(
            os.sep, "/"
        )
    )
    replacement = (
        f'{indent}"build": {{\n'
        f'{indent}  "dockerfile": {dockerfile}\n'
        f"{indent}}}{match.group('comma')}{match.group('tail')}"
    )
    destination_contents = text[: match.start()] + replacement + text[match.end() :]
    copyright_header = (
        _ECLIPSE_COPYRIGHT if operation.copyright_organization == organization else ""
    )
    prefix = f"{copyright_header}\n" if copyright_header else ""
    dockerfile_contents = (
        f"{prefix}{_DOCKERFILE_COMMENT}\nFROM {operation.image}:{tag}\n"
    )
    return dockerfile_contents, destination_contents


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas while preserving strings."""

    result: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_line_comment:
            if character in "\r\n":
                in_line_comment = False
                result.append(character)
            else:
                result.append(" ")
        elif in_block_comment:
            if character == "*" and following == "/":
                in_block_comment = False
                result.extend((" ", " "))
                index += 1
            else:
                result.append("\n" if character in "\r\n" else " ")
        elif in_string:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
            result.append(character)
        elif character == "/" and following == "/":
            in_line_comment = True
            result.extend((" ", " "))
            index += 1
        elif character == "/" and following == "*":
            in_block_comment = True
            result.extend((" ", " "))
            index += 1
        else:
            result.append(character)
        index += 1

    return re.sub(r",\s*([}\]])", r"\1", "".join(result))


def _validate_target(path: Path, operation: MigrateDevcontainerJson) -> None:
    if path.exists() and not path.is_file():
        raise RepoPolicySyncError(f"{operation.dockerfile} must not be a directory")


def _validate_destination(path: Path, operation: MigrateDevcontainerJson) -> None:
    if path.exists() and not path.is_file():
        raise RepoPolicySyncError(f"{operation.destination} must not be a directory")
