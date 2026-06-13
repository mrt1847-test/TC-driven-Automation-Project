from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from slugify import slugify
from sqlmodel import Session, select

from worker.models.db import TestCase, TestCaseStatus
from worker.models.schemas import NormalizedTestCase


TERMINAL_CASE_STATUSES = {
    TestCaseStatus.retired.value,
    TestCaseStatus.deleted.value,
}


def normalize_automation_key(value: object, fallback: str = "case") -> str:
    base = slugify(str(value or "").strip(), separator="_").lower()
    return base or fallback


def unique_automation_key(base: str, reserved_keys: set[str]) -> str:
    candidate = base
    counter = 1
    while candidate in reserved_keys:
        candidate = f"{base}_{counter:03d}"
        counter += 1
    return candidate


def reserve_automation_key(
    raw_key: object,
    *,
    title: str,
    source_id: str,
    reserved_keys: set[str],
) -> str:
    seed = raw_key if str(raw_key or "").strip() else source_id or title
    base = normalize_automation_key(seed)
    return unique_automation_key(base, reserved_keys)


def active_automation_keys(session: Session, project_id: str) -> set[str]:
    return {
        normalize_automation_key(row.automation_key)
        for row in _active_project_cases(session, project_id)
    }


def reserve_normalized_case_keys(
    session: Session,
    project_id: str,
    cases: Iterable[NormalizedTestCase],
) -> list[NormalizedTestCase]:
    reserved_keys = active_automation_keys(session, project_id)
    normalized_cases: list[NormalizedTestCase] = []
    for case in cases:
        automation_key = reserve_automation_key(
            case.automation_key,
            title=case.title,
            source_id=case.source_id,
            reserved_keys=reserved_keys,
        )
        reserved_keys.add(automation_key)
        normalized_cases.append(case.model_copy(update={"automation_key": automation_key}))
    return normalized_cases


def duplicate_active_automation_keys(session: Session, project_id: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in _active_project_cases(session, project_id):
        grouped[normalize_automation_key(row.automation_key)].append(str(row.id or ""))
    return {
        key: sorted(case_ids)
        for key, case_ids in grouped.items()
        if key and len(case_ids) > 1
    }


def assert_unique_active_automation_keys(session: Session, project_id: str) -> None:
    duplicates = duplicate_active_automation_keys(session, project_id)
    if not duplicates:
        return
    details = ", ".join(
        f"{key} ({', '.join(case_ids)})"
        for key, case_ids in sorted(duplicates.items())
    )
    raise ValueError(f"Duplicate active automation_key values in project: {details}")


def _active_project_cases(session: Session, project_id: str) -> list[TestCase]:
    return session.exec(
        select(TestCase).where(
            TestCase.project_id == project_id,
            TestCase.status.not_in(TERMINAL_CASE_STATUSES),
        )
    ).all()
