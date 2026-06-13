from __future__ import annotations

import re

PROTECTED_REGION_BEGIN_PREFIX = '# <tc-protected name="'
PROTECTED_REGION_END = "# </tc-protected>"

_REGION_NAME_RE = r"[A-Za-z0-9_.:-]+"
_BEGIN_RE = re.compile(
    rf'^(?P<indent>[ \t]*)# <tc-protected name="(?P<name>{_REGION_NAME_RE})">\s*$'
)
_END_RE = re.compile(r"^(?P<indent>[ \t]*)# </tc-protected>\s*$")


def protected_region_block(name: str, *, indent: str = "") -> list[str]:
    if not re.fullmatch(_REGION_NAME_RE, name):
        raise ValueError("Protected region name is invalid")
    return [
        f'{indent}{PROTECTED_REGION_BEGIN_PREFIX}{name}">',
        f"{indent}{PROTECTED_REGION_END}",
    ]


def _region_spans(lines: list[str]) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = {}
    index = 0
    while index < len(lines):
        begin = _BEGIN_RE.match(lines[index].rstrip("\r\n"))
        if not begin:
            index += 1
            continue
        name = begin.group("name")
        search = index + 1
        end_index: int | None = None
        while search < len(lines):
            end = _END_RE.match(lines[search].rstrip("\r\n"))
            if end and end.group("indent") == begin.group("indent"):
                end_index = search
                break
            search += 1
        if end_index is None:
            index += 1
            continue
        spans.setdefault(name, []).append((index, end_index))
        index = end_index + 1
    return spans


def merge_protected_regions(planned: str, current: str) -> str:
    planned_lines = planned.splitlines(keepends=True)
    current_lines = current.splitlines(keepends=True)
    planned_spans = _region_spans(planned_lines)
    current_spans = _region_spans(current_lines)
    merged = list(planned_lines)
    replacements: list[tuple[int, int, list[str]]] = []

    for name, spans in planned_spans.items():
        if len(planned_spans[name]) != 1 or len(current_spans.get(name, [])) != 1:
            continue
        planned_start, planned_end = spans[0]
        current_start, current_end = current_spans[name][0]
        replacements.append(
            (planned_start, planned_end, current_lines[current_start + 1:current_end])
        )

    for planned_start, planned_end, region_body in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        merged[planned_start + 1:planned_end] = region_body
    return "".join(merged)


def normalize_protected_regions(content: str) -> str:
    lines = content.splitlines(keepends=True)
    spans = _region_spans(lines)
    normalized = list(lines)
    unique_spans: list[tuple[int, int]] = []
    for region_spans in spans.values():
        if len(region_spans) != 1:
            continue
        unique_spans.append(region_spans[0])

    for start, end in sorted(unique_spans, key=lambda item: item[0], reverse=True):
        normalized[start + 1:end] = []
    return "".join(normalized)
