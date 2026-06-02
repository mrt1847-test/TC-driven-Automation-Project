from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    RawAction,
    SelectorCandidate,
    SelectorCandidateType,
)

_ROLE_PATTERN = re.compile(
    r"get_by_role\(\s*['\"](?P<role>[^'\"]+)['\"](?:\s*,\s*name\s*=\s*['\"](?P<name>[^'\"]+)['\"])?",
    re.IGNORECASE,
)
_TEXT_PATTERN = re.compile(r"get_by_(?:text|label|placeholder)\(\s*['\"](?P<text>[^'\"]+)['\"]", re.IGNORECASE)
_TEST_ID_PATTERN = re.compile(r"get_by_test_id\(\s*['\"](?P<test_id>[^'\"]+)['\"]", re.IGNORECASE)
_LOCATOR_PATTERN = re.compile(r"locator\(\s*(?P<quote>['\"])(?P<selector>.*?)(?P=quote)", re.IGNORECASE)
_DATA_TEST_ID_PATTERN = re.compile(r"data-testid\s*=\s*['\"]?(?P<test_id>[^'\"\]]+)", re.IGNORECASE)

_RUN_ARTIFACT_PRIORITY = {
    ArtifactAssetType.trajectory.value: 0,
    ArtifactAssetType.final_script.value: 1,
    ArtifactAssetType.metadata.value: 2,
    ArtifactAssetType.log.value: 3,
}


@dataclass(frozen=True)
class _CandidateSeed:
    selector_type: str
    selector_value: str
    confidence: float
    reason: str


def _candidate_seeds(selector: str) -> list[_CandidateSeed]:
    seeds: list[_CandidateSeed] = []

    role_match = _ROLE_PATTERN.search(selector)
    if role_match:
        role = role_match.group("role")
        name = role_match.group("name")
        value = f"{role}[name='{name}']" if name else role
        seeds.append(_CandidateSeed(SelectorCandidateType.role.value, value, 0.95, "playwright_role_locator"))

    text_match = _TEXT_PATTERN.search(selector)
    if text_match:
        seeds.append(_CandidateSeed(
            SelectorCandidateType.text.value,
            text_match.group("text"),
            0.82,
            "playwright_text_locator",
        ))

    test_id_match = _TEST_ID_PATTERN.search(selector)
    if test_id_match:
        seeds.append(_CandidateSeed(
            SelectorCandidateType.test_id.value,
            test_id_match.group("test_id"),
            0.97,
            "playwright_test_id_locator",
        ))

    locator_match = _LOCATOR_PATTERN.search(selector)
    if locator_match:
        locator_value = locator_match.group("selector").strip()
        lowered = locator_value.lower()
        data_test_id_match = _DATA_TEST_ID_PATTERN.search(locator_value)
        if data_test_id_match:
            seeds.append(_CandidateSeed(
                SelectorCandidateType.test_id.value,
                data_test_id_match.group("test_id"),
                0.9,
                "css_data_test_id_locator",
            ))
        elif lowered.startswith("xpath="):
            seeds.append(_CandidateSeed(
                SelectorCandidateType.xpath.value,
                locator_value[6:],
                0.64,
                "playwright_xpath_locator",
            ))
        elif locator_value.startswith("//") or locator_value.startswith("(//"):
            seeds.append(_CandidateSeed(
                SelectorCandidateType.xpath.value,
                locator_value,
                0.64,
                "xpath_locator",
            ))
        elif lowered.startswith("text="):
            seeds.append(_CandidateSeed(
                SelectorCandidateType.text.value,
                locator_value[5:],
                0.72,
                "playwright_text_selector",
            ))
        else:
            seeds.append(_CandidateSeed(
                SelectorCandidateType.css.value,
                locator_value,
                0.68,
                "css_locator",
            ))

    unique: list[_CandidateSeed] = []
    seen: set[tuple[str, str]] = set()
    for seed in seeds:
        key = (seed.selector_type, seed.selector_value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(seed)
    return unique


def _source_artifact_id_for_action(session: Session, action: RawAction) -> str | None:
    action_assets = session.exec(
        select(ArtifactAsset)
        .where(ArtifactAsset.source_type == ArtifactAssetSourceType.raw_action.value)
        .where(ArtifactAsset.source_id == action.id)
    ).all()
    if action_assets:
        return action_assets[0].id

    run_assets = session.exec(
        select(ArtifactAsset)
        .where(ArtifactAsset.source_type == ArtifactAssetSourceType.webwright_run.value)
        .where(ArtifactAsset.source_id == action.webwright_run_id)
    ).all()
    if not run_assets:
        return None
    return sorted(run_assets, key=lambda asset: _RUN_ARTIFACT_PRIORITY.get(asset.artifact_type, 99))[0].id


def extract_selector_candidates_for_run(session: Session, run_id: str) -> list[SelectorCandidate]:
    actions = session.exec(
        select(RawAction).where(RawAction.webwright_run_id == run_id).order_by(RawAction.order_index)
    ).all()
    if not actions:
        return []

    for action in actions:
        existing = session.exec(select(SelectorCandidate).where(SelectorCandidate.raw_action_id == action.id)).all()
        for candidate in existing:
            session.delete(candidate)

    candidates: list[SelectorCandidate] = []
    for action in actions:
        if not action.selector:
            continue
        source_artifact_id = _source_artifact_id_for_action(session, action)
        for seed in _candidate_seeds(action.selector):
            metadata = {
                "run_id": action.webwright_run_id,
                "raw_action_id": action.id,
                "action_type": action.type,
                "source_selector": action.selector,
                "source_line": action.source_line,
                "reason": seed.reason,
            }
            candidate = SelectorCandidate(
                id=new_id("sel"),
                raw_action_id=action.id,
                selector_type=seed.selector_type,
                selector_value=seed.selector_value,
                confidence=seed.confidence,
                source_artifact_id=source_artifact_id,
                metadata_json=json.dumps(metadata, sort_keys=True),
            )
            session.add(candidate)
            candidates.append(candidate)

    session.commit()
    for candidate in candidates:
        session.refresh(candidate)
    return candidates
