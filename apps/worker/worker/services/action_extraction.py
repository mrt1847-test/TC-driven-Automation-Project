from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import RawAction, WebwrightRun
from worker.models.schemas import ActionItem

ACTION_PATTERNS = [
    ("goto", re.compile(r"page\.goto\(\s*['\"]([^'\"]+)['\"]")),
    ("click", re.compile(r"\.click\(\s*\)")),
    ("fill", re.compile(r"\.fill\(\s*['\"]([^'\"]*)['\"]\s*\)")),
    ("press", re.compile(r"\.press\(\s*['\"]([^'\"]+)['\"]\s*\)")),
    ("check", re.compile(r"\.check\(\s*\)")),
    ("uncheck", re.compile(r"\.uncheck\(\s*\)")),
    ("hover", re.compile(r"\.hover\(\s*\)")),
    ("wait", re.compile(r"page\.wait_for_timeout\(\s*(\d+)")),
    ("assert_url", re.compile(r"expect\(page\)\.to_have_url\(\s*re?\.?compile\(\s*['\"]([^'\"]+)['\"]")),
    ("assert_text", re.compile(r"expect\(.*?\)\.to_have_text\(\s*['\"]([^'\"]+)['\"]")),
    ("assert_visible", re.compile(r"expect\(.*?\)\.to_be_visible\(\s*\)")),
    ("assert_hidden", re.compile(r"expect\(.*?\).to_be_hidden\(\s*\)")),
    ("wait_for_request", re.compile(r"page\.wait_for_request\(\s*re?\.?compile\(\s*['\"]([^'\"]+)['\"]")),
    ("wait_for_response", re.compile(r"page\.wait_for_response\(\s*re?\.?compile\(\s*['\"]([^'\"]+)['\"]")),
]

LOCATOR_PATTERN = re.compile(r"(page(?:\.locator\([^)]+\)|\.get_by_[a-z_]+\([^)]+\))(?:\.[a-z_]+\([^)]*\))*)")


def extract_actions_from_script(script_path: str, automation_key: str, run_id: str, session: Session) -> list[ActionItem]:
    path = Path(script_path)
    if not path.exists():
        return []

    session.exec(select(RawAction).where(RawAction.webwright_run_id == run_id)).all()
    for action in session.exec(select(RawAction).where(RawAction.webwright_run_id == run_id)).all():
        session.delete(action)

    lines = path.read_text(encoding="utf-8").splitlines()
    actions: list[ActionItem] = []
    order = 1

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        locator_match = LOCATOR_PATTERN.search(stripped)
        selector = locator_match.group(1) if locator_match else None

        matched = False
        for action_type, pattern in ACTION_PATTERNS:
            m = pattern.search(stripped)
            if m:
                value = m.group(1) if m.lastindex else None
                if action_type == "goto":
                    selector = None
                    target = value
                elif action_type == "click":
                    target = "click target"
                else:
                    target = value or action_type
                item = ActionItem(
                    id=new_id("act"),
                    type=action_type,
                    target=target,
                    selector=selector,
                    value=value if action_type in {"fill", "press"} else None,
                    source_line=line_no,
                    order_index=order,
                )
                actions.append(item)
                db_action = RawAction(
                    id=item.id,
                    webwright_run_id=run_id,
                    automation_key=automation_key,
                    order_index=order,
                    type=item.type,
                    target=item.target,
                    selector=item.selector,
                    value=item.value,
                    source_line=item.source_line,
                )
                session.add(db_action)
                order += 1
                matched = True
                break
        if not matched and "expect(" in stripped:
            item = ActionItem(
                id=new_id("act"),
                type="custom_code",
                target=stripped[:120],
                selector=selector,
                source_line=line_no,
                order_index=order,
            )
            actions.append(item)
            session.add(RawAction(
                id=item.id,
                webwright_run_id=run_id,
                automation_key=automation_key,
                order_index=order,
                type=item.type,
                target=item.target,
                selector=item.selector,
                source_line=item.source_line,
            ))
            order += 1

    session.commit()
    return actions


def enrich_from_trajectory(actions: list[ActionItem], trajectory_path: str | None) -> list[ActionItem]:
    if not trajectory_path or not Path(trajectory_path).exists():
        return actions
    try:
        data = json.loads(Path(trajectory_path).read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > len(actions):
            pass
    except Exception:
        pass
    return actions
