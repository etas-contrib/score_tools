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

"""Small helpers for parsing and comparing bzlmod versions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import BazelDependencyCondition

BazelVersion = tuple[int, int, int]


@dataclass(frozen=True)
class StarlarkCall:
    """A function call found outside Starlark strings and comments."""

    start: int
    body_start: int
    body_end: int


@dataclass(frozen=True)
class StarlarkStringArgument:
    """A quoted keyword argument and its value span in the source text."""

    key: str
    value: str
    value_start: int
    value_end: int


_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_CONDITION = re.compile(
    r"\A\s*([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*(==|!=|<=|>=|<|>)\s*"
    r"((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\s*\Z"
)


def parse_bazel_version(value: str) -> BazelVersion | None:
    """Parse a strict major.minor.patch version."""

    match = _VERSION.fullmatch(value)
    return tuple(int(component) for component in match.groups()) if match else None


def find_starlark_calls(text: str, function_name: str) -> tuple[StarlarkCall, ...]:
    """Find calls to ``function_name`` while ignoring strings and comments."""

    masked = _mask_starlark(text)
    function = re.compile(rf"\b{re.escape(function_name)}\s*\(")
    calls: list[StarlarkCall] = []
    for match in function.finditer(masked):
        opening = masked.find("(", match.start(), match.end())
        depth = 0
        for index in range(opening, len(masked)):
            character = masked[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    calls.append(StarlarkCall(match.start(), opening + 1, index))
                    break
    return tuple(calls)


def starlark_string_arguments(
    text: str, call: StarlarkCall, key: str
) -> tuple[StarlarkStringArgument, ...]:
    """Find direct quoted ``key = "value"`` arguments in one call."""

    arguments: list[StarlarkStringArgument] = []
    index = call.body_start
    depth = 0
    while index < call.body_end:
        character = text[index]
        if character == "#":
            index = _skip_comment(text, index)
            continue
        if character in "'\"":
            index = _skip_string(text, index)
            continue
        if character == "(":
            depth += 1
            index += 1
            continue
        if character == ")":
            depth -= 1
            index += 1
            continue
        if depth != 0 or not (character.isalpha() or character == "_"):
            index += 1
            continue

        key_start = index
        index += 1
        while index < call.body_end and (text[index].isalnum() or text[index] == "_"):
            index += 1
        if text[key_start:index] != key:
            continue
        index = _skip_whitespace_and_comments(text, index)
        if index >= call.body_end or text[index] != "=":
            continue
        index = _skip_whitespace_and_comments(text, index + 1)
        if index >= call.body_end or text[index] not in "'\"":
            continue
        delimiter = _string_delimiter(text, index)
        value_start = index + len(delimiter)
        value_end = _skip_string(text, index)
        content_end = value_end - len(delimiter)
        if value_end <= value_start or text[content_end:value_end] != delimiter:
            continue
        arguments.append(
            StarlarkStringArgument(
                key,
                text[value_start:content_end],
                value_start,
                content_end,
            )
        )
        index = value_end
    return tuple(arguments)


def _mask_starlark(text: str) -> str:
    masked = list(text)
    index = 0
    while index < len(text):
        character = text[index]
        if character == "#":
            index = _mask_comment(text, masked, index)
        elif character in "'\"":
            index = _mask_string(text, masked, index)
        else:
            index += 1
    return "".join(masked)


def _mask_comment(text: str, masked: list[str], start: int) -> int:
    index = start
    while index < len(text) and text[index] not in "\r\n":
        masked[index] = " "
        index += 1
    return index


def _mask_string(text: str, masked: list[str], start: int) -> int:
    delimiter = _string_delimiter(text, start)
    for offset in range(len(delimiter)):
        if start + offset < len(masked) and text[start + offset] not in "\r\n":
            masked[start + offset] = " "
    index = start + len(delimiter)
    escaped = False
    while index < len(text):
        character = text[index]
        if character not in "\r\n":
            masked[index] = " "
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif text.startswith(delimiter, index):
            for offset in range(len(delimiter)):
                if index + offset < len(masked) and text[index + offset] not in "\r\n":
                    masked[index + offset] = " "
            return index + len(delimiter)
        index += 1
    return index


def _skip_comment(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index] not in "\r\n":
        index += 1
    return index


def _skip_string(text: str, start: int) -> int:
    delimiter = _string_delimiter(text, start)
    index = start + len(delimiter)
    escaped = False
    while index < len(text):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif text.startswith(delimiter, index):
            return index + len(delimiter)
        index += 1
    return index


def _string_delimiter(text: str, start: int) -> str:
    quote = text[start]
    return quote * 3 if text.startswith(quote * 3, start) else quote


def _skip_whitespace_and_comments(text: str, start: int) -> int:
    index = start
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text[index] == "#":
            index = _skip_comment(text, index)
        else:
            break
    return index


def parse_bazel_dependency_condition(value: str) -> BazelDependencyCondition | None:
    """Parse ``module OP major.minor.patch`` condition syntax."""

    match = _CONDITION.fullmatch(value)
    if match is None:
        return None
    version = parse_bazel_version(match.group(3))
    assert version is not None
    return BazelDependencyCondition(match.group(1), match.group(2), version)


def matches_bazel_dependency_condition(
    actual: BazelVersion, condition: BazelDependencyCondition
) -> bool:
    """Compare one parsed dependency version with a policy condition."""

    if condition.operator == "==":
        return actual == condition.version
    if condition.operator == "!=":
        return actual != condition.version
    if condition.operator == "<":
        return actual < condition.version
    if condition.operator == "<=":
        return actual <= condition.version
    if condition.operator == ">":
        return actual > condition.version
    if condition.operator == ">=":
        return actual >= condition.version
    raise ValueError(f"unsupported Bazel version operator: {condition.operator}")
